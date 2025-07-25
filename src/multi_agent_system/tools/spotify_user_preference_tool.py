import json
import os
import base64
from typing import Type, Dict, List, Optional, Any
from datetime import datetime
from collections import Counter
import random

from crewai.tools import BaseTool
import requests
from pydantic import BaseModel, Field


class SpotifyTokenManager:
    """Simple token manager for Spotify API with automatic token refresh."""
    
    def __init__(self):
        self.client_id = os.getenv("SPOTIFY_CLIENT_ID")
        self.client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
        self._current_token = None
        self._token_expires_at = None
    
    def get_access_token(self, refresh_token: str) -> Optional[str]:
        """Get valid access token, refreshing if necessary."""
        # Check if the current token is still valid (with 5 minute buffer for safety)
        if self._current_token and self._token_expires_at:
            buffer_seconds = 300
            if datetime.now().timestamp() < (self._token_expires_at - buffer_seconds):
                return self._current_token
        
        # Refresh token
        new_token_data = self._refresh_access_token(refresh_token)
        if new_token_data:
            self._current_token = new_token_data["access_token"]
            # Token expires in 1 hour
            self._token_expires_at = datetime.now().timestamp() + 3600
            return self._current_token
        
        return None
    
    def _refresh_access_token(self, refresh_token: str) -> Optional[Dict[str, Any]]:
        """Refresh access token using refresh token."""
        if not self.client_id or not self.client_secret:
            print("Missing SPOTIFY_CLIENT_ID or SPOTIFY_CLIENT_SECRET environment variables")
            return None
        
        try:
            # Prepare authorization header
            auth_string = f"{self.client_id}:{self.client_secret}"
            auth_b64 = base64.b64encode(auth_string.encode("ascii")).decode("ascii")
            
            headers = {
                "Authorization": f"Basic {auth_b64}",
                "Content-Type": "application/x-www-form-urlencoded"
            }
            
            data = {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token
            }
            
            response = requests.post("https://accounts.spotify.com/api/token", headers=headers, data=data, timeout=10)
            response.raise_for_status()
            
            return response.json()
            
        except requests.exceptions.RequestException as e:
            print(f"Error refreshing Spotify token: {e}")
            return None
        except Exception as e:
            print(f"Unexpected error in token refresh: {e}")
            return None


class SpotifyUserPreferenceToolInput(BaseModel):
    """Input schema for Spotify Podcast Preference Tool"""
    analysis_depth: str = Field(default="detailed", description="Analysis depth: 'basic', 'detailed', or 'comprehensive'")
    episodes_per_show: int = Field(default=30, description="Number of episodes to fetch per saved show for recommendations")
    max_episode_candidates: int = Field(default=30, description="Maximum total episode candidates to return")


class SpotifyUserPreferenceTool(BaseTool):
    name: str = "Spotify Podcast Preference Analyzer"
    description: str = """Analyze user podcast preferences from Spotify based on saved podcast shows and discover episode candidates.
    
    This tool focuses exclusively on podcast content analysis to understand:
    - Podcast genres inferred from show content
    - Preferred podcast publishers and content types
    - Show characteristics and themes
    - Episode candidates for personalized recommendations
    
    The tool also discovers episode candidates by fetching episodes from the user's saved shows,
    using a weighted selection strategy that prioritizes recent content while maintaining variety.
    
    Requires a valid Spotify access token with appropriate scopes for user data access."""
    args_schema: Type[BaseModel] = SpotifyUserPreferenceToolInput
    
    def __init__(self):
        super().__init__()
        self._genre_mapping = self._build_podcast_genre_mapping()
        self._token_manager = SpotifyTokenManager()

    def _run(self, analysis_depth: str = "detailed",
             episodes_per_show: int = 30,
             max_episode_candidates: int = 30) -> str:
        """Execute the Spotify podcast preference analysis."""

        try:
            refresh_token = os.getenv("SPOTIFY_REFRESH_TOKEN")
            if not refresh_token:
                return json.dumps({
                    "error": "SPOTIFY_REFRESH_TOKEN environment variable not set. Please set this variable with your Spotify refresh token.",
                    "preferences": {}
                })

            access_token = self._token_manager.get_access_token(refresh_token)
            if not access_token:
                return json.dumps({
                    "error": "Unable to obtain valid access token. Check refresh token validity and client credentials.",
                    "preferences": {}
                })

            saved_shows = self._get_saved_shows(access_token)

            episode_candidates = self._discover_episode_candidates(
                saved_shows, access_token, episodes_per_show, max_episode_candidates
            )

            # Create episodes cache from the episode discovery process to avoid duplicate API calls
            episodes_cache = {}
            for candidate in episode_candidates:
                show_id = candidate.get("show_id")
                if show_id:
                    if show_id not in episodes_cache:
                        episodes_cache[show_id] = []
                    episodes_cache[show_id].append(candidate)

            show_analysis = self._analyze_show_preferences(saved_shows, access_token, episodes_cache)

            # Generate listening patterns from saved shows only
            listening_patterns = self._analyze_listening_patterns_from_shows(saved_shows)

            # Calculate confidence
            confidence_score = self._calculate_confidence_score(
                saved_shows, show_analysis
            )

            # Format simplified output
            preferences = self._format_analysis_output(
                show_analysis, listening_patterns, confidence_score, analysis_depth
            )

            # Add episode candidates and saved shows
            preferences["saved_shows"] = self._summarize_saved_shows(saved_shows)
            preferences["episode_candidates"] = episode_candidates
            preferences["total_candidates"] = len(episode_candidates)

            return json.dumps(preferences, indent=2)

        except Exception as e:
            return json.dumps({"error": f"Failed to analyze Spotify podcast preferences: {str(e)}", "preferences": {}})

    def _build_podcast_genre_mapping(self) -> Dict[str, List[str]]:
        """Build mapping of podcast categories to standardized genres."""
        return {
            "comedy": ["comedy", "humor", "entertainment"],
            "news": ["news", "politics", "current events", "journalism"],
            "business": ["business", "entrepreneurship", "finance", "investing"],
            "technology": ["technology", "tech", "science", "innovation"],
            "education": ["education", "learning", "academic", "educational"],
            "health": ["health", "fitness", "wellness", "mental health", "medicine"],
            "true_crime": ["true crime", "crime", "mystery", "investigation"],
            "history": ["history", "historical", "culture", "documentary"],
            "society": ["society", "culture", "philosophy", "religion", "spirituality"],
            "arts": ["arts", "music", "film", "literature", "creative"],
            "sports": ["sports", "athletics", "fitness", "recreation"],
            "lifestyle": ["lifestyle", "personal development", "self-help", "relationships"],
            "storytelling": ["storytelling", "fiction", "drama", "narrative"],
            "interview": ["interview", "talk show", "conversation", "discussion"]
        }
    
    def _infer_genre_from_text(self, text: str) -> List[str]:
        """Infer podcast genres from text (name/description) using keyword matching."""
        if not text:
            return []
        
        text_lower = text.lower()
        matched_genres = []
        
        for genre, keywords in self._genre_mapping.items():
            for keyword in keywords:
                if keyword in text_lower:
                    matched_genres.append(genre)
                    break  # Only add genre once per show
        
        return matched_genres
    
    def _make_spotify_request(self, endpoint: str, access_token: str, params: Dict = None) -> Optional[Dict]:
        """Make authenticated request to Spotify API."""
        try:
            url = f"https://api.spotify.com/v1{endpoint}"
            headers = {"Authorization": f"Bearer {access_token}"}
            
            response = requests.get(url, headers=headers, params=params or {}, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Spotify API request failed: {e}")
            return None
    
    def _get_saved_shows(self, access_token: str) -> List[Dict]:
        """Get user's saved podcast shows."""
        saved_shows = []
        offset = 0
        max_return_items = 50  # Spotify API limit
        
        while True:
            data = self._make_spotify_request(
                "/me/shows",
                access_token,
                {"limit": max_return_items, "offset": offset}
            )
            
            if not data or not data.get("items"):
                break
                
            saved_shows.extend(data["items"])
            
            if len(data["items"]) < 50:
                break
                
            offset += 50
        
        return saved_shows
    

    def _summarize_saved_shows(self, saved_shows: List[Dict]) -> List[Dict[str, Any]]:
        """Summarize saved podcast shows in a simplified format."""
        summaries: List[Dict[str, Any]] = []
        for item in saved_shows:
            show = item.get("show", {}) if isinstance(item, dict) else {}
            show_id = show.get("id")
            if not show_id:
                continue
            summaries.append({
                "id": show_id,
                "title": show.get("name"),
                "publisher": show.get("publisher"),
                "url": show.get('uri')
            })
        return summaries

    def _get_episode_durations_from_episodes(self, episodes: List[Dict]) -> List[int]:
        """Extract episode durations from already fetched episode data."""
        durations = []
        for episode in episodes:
            duration_minutes = episode.get("duration_minutes", 0)
            if duration_minutes > 0:
                durations.append(duration_minutes)
        return durations
    
    def _get_show_episodes(self, show_id: str, access_token: str, limit: int = 50) -> List[Dict]:
        """Get episodes for a specific show for content discovery."""
        try:
            data = self._make_spotify_request(
                f"/shows/{show_id}/episodes",
                access_token,
                {"limit": min(limit, 50)}
            )
            
            if not data or not data.get("items"):
                return []
            
            episodes = []
            for episode in data["items"]:
                episodes.append({
                    "id": episode.get("id"),
                    "title": episode.get("name"),
                    "description": episode.get("description", ""),
                    "duration_minutes": episode.get("duration_ms", 0) // 60000,
                    "release_date": episode.get("release_date"),
                    "url": episode.get("external_urls", {}).get("spotify"),
                    "explicit": episode.get("explicit", False),
                    "show_id": show_id
                })
            
            return episodes
            
        except Exception as e:
            print(f"Error fetching episodes for show {show_id}: {e}")
            return []
    
    def _discover_episode_candidates(self, saved_shows: List[Dict], access_token: str, 
                                   episodes_per_show: int = 50, max_candidates: int = 100) -> List[Dict]:
        """Discover episode candidates using simple random sampling."""
        all_episodes = []
        
        for show_item in saved_shows:
            show = show_item.get("show", {})
            show_id = show.get("id")
            show_name = show.get("name", "Unknown Show")
            
            if not show_id:
                continue
                
            episodes = self._get_show_episodes(show_id, access_token, episodes_per_show)
            
            for episode in episodes:
                episode["show_name"] = show_name
                episode["publisher"] = show.get("publisher")
                episode["genres"] = self._infer_genre_from_text(f"{episode.get('title', '')} {episode.get('description', '')}")
            
            all_episodes.extend(episodes)
        
        selected_episodes = self._apply_episode_selection_strategy(all_episodes, max_candidates)
        
        print(f"Selected {len(selected_episodes)} episode candidates from {len(all_episodes)} total episodes")
        return selected_episodes
    
    def _apply_episode_selection_strategy(self, episodes: List[Dict], max_candidates: int) -> List[Dict]:
        """Apply simple random sampling for episode selection."""
        if len(episodes) <= max_candidates:
            return episodes
        
        return random.sample(episodes, max_candidates)
    
    def _analyze_show_preferences(self, saved_shows: List[Dict], access_token: str, 
                                 episodes_cache: Dict[str, List[Dict]] = None) -> Dict[str, Any]:
        """Analyze preferences from saved podcast shows using cached episode data when available."""
        if not saved_shows:
            return {
                "genres": {},
                "publishers": {},
                "languages": {},
                "explicit_tolerance": 0.0,
                "avg_episode_duration": 0,
                "total_shows": 0
            }
        
        genre_counts = Counter()
        publisher_counts = Counter()
        language_counts = Counter()
        explicit_count = 0
        episode_durations = []
        
        for show_item in saved_shows:
            show = show_item.get("show", {})
            if not show:
                continue
            
            # Infer genres from show name and description
            show_name = show.get("name", "")
            show_description = show.get("description", "")
            text_to_analyze = f"{show_name} {show_description}"
            
            inferred_genres = self._infer_genre_from_text(text_to_analyze)
            for genre in inferred_genres:
                genre_counts[genre] += 1
            
            # Publisher
            publisher = show.get("publisher", "Unknown")
            if publisher != "Unknown":
                publisher_counts[publisher] += 1
            
            # Language
            languages = show.get("languages", ["en"])
            for lang in languages:
                language_counts[lang] += 1
            
            # Explicit content
            if show.get("explicit", False):
                explicit_count += 1
            
            # Use cached episode data if available, otherwise fetch data using API
            show_id = show.get("id")
            if show_id:
                if episodes_cache and show_id in episodes_cache:
                    # Use cached episodes for duration analysis
                    cached_episodes = episodes_cache[show_id]
                    episode_durations_for_show = self._get_episode_durations_from_episodes(cached_episodes)
                else:
                    # Fallback: fetch episodes just for duration (sample size)
                    episodes = self._get_show_episodes(show_id, access_token, limit=10)
                    episode_durations_for_show = self._get_episode_durations_from_episodes(episodes)
                
                episode_durations.extend(episode_durations_for_show)
        
        # Calculate preference scores
        total_shows = len(saved_shows)
        genre_prefs = {genre: count / total_shows for genre, count in genre_counts.most_common()}
        
        return {
            "genres": genre_prefs,
            "publishers": dict(publisher_counts.most_common(10)),
            "languages": dict(language_counts.most_common()),
            "explicit_tolerance": explicit_count / total_shows if total_shows > 0 else 0.0,
            "avg_episode_duration": sum(episode_durations) // len(episode_durations) if episode_durations else 0,
            "total_shows": total_shows,
            "episode_duration_range": {
                "min": min(episode_durations) if episode_durations else 0,
                "max": max(episode_durations) if episode_durations else 0,
                "preferred": sum(episode_durations) // len(episode_durations) if episode_durations else 0,
                "sample_count": len(episode_durations)
            }
        }
    
    
    def _analyze_listening_patterns_from_shows(self, saved_shows: List[Dict]) -> Dict[str, Any]:
        """Analyze listening patterns from saved shows only (limited data).
        
        Since Spotify API doesn't provide recent podcast episodes,
        we can only infer basic patterns from saved show metadata.
        """
        patterns = {
            "listening_frequency": "unknown",
            "preferred_times": ["unknown"],
            "completion_rate": "unknown",
            "discovery_tendency": 0.0,
            "show_diversity": 0.0,
            "total_saved_shows": len(saved_shows)
        }
        
        if not saved_shows:
            patterns["listening_frequency"] = "none"
            return patterns
        
        # Analyze show diversity (different publishers/genres)
        publishers = set()
        for item in saved_shows:
            show = item.get("show", {})
            publisher = show.get("publisher")
            if publisher:
                publishers.add(publisher)
        
        if len(saved_shows) > 0:
            patterns["show_diversity"] = len(publishers) / len(saved_shows)
        
        # Infer listening frequency from number of saved shows
        if len(saved_shows) >= 20:
            patterns["listening_frequency"] = "heavy_listener"
        elif len(saved_shows) >= 10:
            patterns["listening_frequency"] = "regular_listener"
        elif len(saved_shows) >= 3:
            patterns["listening_frequency"] = "casual_listener"
        else:
            patterns["listening_frequency"] = "light_listener"
        
        return patterns
    
    def _calculate_confidence_score(self, saved_shows: List[Dict], show_analysis: Dict) -> float:
        """Calculate confidence score for the analysis."""
        confidence_factors = []
        
        show_count = len(saved_shows)
        if show_count >= 10:
            confidence_factors.append(0.3)
        elif show_count >= 5:
            confidence_factors.append(0.2)
        elif show_count >= 1:
            confidence_factors.append(0.1)
        else:
            confidence_factors.append(0.0)
        
        # Diversity of genres
        genre_count = len(show_analysis.get("genres", {}))
        if genre_count >= 5:
            confidence_factors.append(0.2)
        elif genre_count >= 3:
            confidence_factors.append(0.15)
        elif genre_count >= 1:
            confidence_factors.append(0.1)
        else:
            confidence_factors.append(0.0)
        
        # Show metadata quality (since we can't get recent episodes)
        shows_with_descriptions = sum(1 for item in saved_shows 
                                    if item.get("show", {}).get("description"))
        if shows_with_descriptions >= len(saved_shows) * 0.8:
            confidence_factors.append(0.2)
        elif shows_with_descriptions >= len(saved_shows) * 0.5:
            confidence_factors.append(0.15)
        elif shows_with_descriptions > 0:
            confidence_factors.append(0.1)
        else:
            confidence_factors.append(0.05)
        
        # Episode duration data availability
        if show_analysis.get("avg_episode_duration", 0) > 0:
            confidence_factors.append(0.15)
        else:
            confidence_factors.append(0.05)
        
        # Language diversity
        lang_count = len(show_analysis.get("languages", {}))
        if lang_count >= 2:
            confidence_factors.append(0.1)
        else:
            confidence_factors.append(0.05)
        
        # Publisher diversity
        publisher_count = len(show_analysis.get("publishers", {}))
        if publisher_count >= 5:
            confidence_factors.append(0.05)
        else:
            confidence_factors.append(0.02)
        
        return min(1.0, sum(confidence_factors))
    
    def _format_analysis_output(self, show_analysis: Dict, listening_patterns: Dict, 
                              confidence_score: float, analysis_depth: str) -> Dict:
        """Format the analysis results in a simplified structure."""
        
        genres = show_analysis.get("genres", {})
        avg_duration = show_analysis.get("avg_episode_duration", 0)
        
        return {
            "platform": "spotify",
            "analysis_depth": analysis_depth,
            "confidence_score": confidence_score,
            
            # Simplified core preferences
            "genres": genres,
            "preferred_duration_minutes": avg_duration,
            "publishers": dict(list(show_analysis.get("publishers", {}).items())[:5]),  # Top 5 only
            "languages": show_analysis.get("languages", {}),
            "explicit_tolerance": show_analysis.get("explicit_tolerance", 0.0),
            
            # Summary insights
            "primary_genre": max(genres.items(), key=lambda x: x[1])[0] if genres else "unknown",
            "listening_frequency": listening_patterns.get("listening_frequency", "unknown"),
            "total_shows": show_analysis.get("total_shows", 0)
        }
