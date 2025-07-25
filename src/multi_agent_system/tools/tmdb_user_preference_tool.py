import json
import os
from datetime import datetime
from typing import Type, Dict, List, Optional, Any

from crewai.tools import BaseTool
import requests
from pydantic import BaseModel, Field


class TMDBUserPreferenceToolInput(BaseModel):
    """Input schema for TMDB User Preference Tool"""
    user_id: str = Field(..., description="TMDB user ID or username for preference analysis")
    analysis_depth: str = Field(default="comprehensive", description="Analysis depth: 'basic', 'detailed', or 'comprehensive'")


class TMDBUserPreferenceTool(BaseTool):
    name: str = "TMDB User Preference Analyzer"
    description: str = """Analyze user preferences from TMDB profile including watchlists, ratings, and favorite content.
    Requires TMDB_SESSION_TOKEN environment variable for authenticated access to user account data."""
    args_schema: Type[BaseModel] = TMDBUserPreferenceToolInput
    
    def __init__(self):
        super().__init__()
        self._api_key = os.environ.get("TMDB_API_KEY")
        self._session_token = os.environ.get("TMDB_SESSION_TOKEN")
        self._genre_cache = {}  # Cache genres during analysis
    
    def _make_api_request(self, endpoint: str, params: Dict = None) -> Optional[Dict]:
        """Make an API request to TMDB."""
        try:
            url = f"{'https://api.themoviedb.org/3'}{endpoint}"
            default_params = {"api_key": self._api_key}
            if params:
                default_params.update(params)
            
            response = requests.get(url, params=default_params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            return data
        except requests.exceptions.RequestException as e:
            print(f"TMDB API request failed for {endpoint}: {e}")
            return None
        except Exception as e:
            print(f"Unexpected error in TMDB API request: {e}")
            return None

    def _run(self, user_id: str, analysis_depth: str = "comprehensive") -> str:
        """Analyze user preferences from TMDB profile data."""
        try:
            if not self._api_key:
                return json.dumps({"error": "TMDB_API_KEY not set", "preferences": {}})

            if not self._session_token:
                return json.dumps({
                    "error": "TMDB_SESSION_TOKEN not set. This tool requires authenticated access to user data.",
                    "preferences": {}
                })

            account_details = self._get_account_details()
            if not account_details:
                return json.dumps({
                    "error": "Failed to retrieve account details. Check session token validity.",
                    "preferences": {}
                })

            # Always analyze both movies and TV shows
            content_types = ["movie", "tv"]
            
            preferences = {
                "user_id": user_id,
                "account_details": {
                    "id": account_details.get("id"),
                    "username": account_details.get("username", user_id),
                    "name": account_details.get("name", ""),
                    "include_adult": account_details.get("include_adult", False)
                },
                "analysis_depth": analysis_depth,
                "content_types_analyzed": content_types,
            }

            # Analyze different aspects based on analysis depth
            if "movie" in content_types:
                movie_prefs = self._analyze_movie_preferences(account_details.get("id"), analysis_depth)
                if movie_prefs:
                    preferences["movie_preferences"] = movie_prefs
                else:
                    preferences["movie_preferences"] = {"error": "No movie data available or failed to retrieve it"}

            if "tv" in content_types:
                tv_prefs = self._analyze_tv_preferences(account_details.get("id"), analysis_depth)
                if tv_prefs:
                    preferences["tv_preferences"] = tv_prefs
                else:
                    preferences["tv_preferences"] = {"error": "No TV data available or failed to retrieve it"}

            preferences["overall_insights"] = self._generate_overall_insights(preferences)
            preferences["confidence_score"] = self._calculate_confidence_score(preferences)

            return json.dumps(preferences, indent=2)

        except Exception as e:
            return json.dumps({"error": f"Error analyzing user preferences: {str(e)}", "preferences": {}})
    
    def _get_account_details(self) -> Optional[Dict]:
        endpoint = "/account"
        params = {"session_id": self._session_token}
        return self._make_api_request(endpoint, params)

    def _analyze_movie_preferences(self, account_id: int, analysis_depth: str) -> Optional[Dict[str, Any]]:
        return self._analyze_content_preferences(account_id, "movies", analysis_depth)

    def _analyze_tv_preferences(self, account_id: int, analysis_depth: str) -> Optional[Dict[str, Any]]:
        return self._analyze_content_preferences(account_id, "tv", analysis_depth)
    
    def _analyze_content_preferences(self, account_id: int, content_type: str, analysis_depth: str) -> Optional[Dict[str, Any]]:
        """Analyze content preferences from user's TMDB data for movies or TV shows."""
        try:
            favorites = self._get_user_favorites(account_id, content_type)
            rated_content = self._get_user_rated_content(account_id, content_type)
            watchlist = self._get_user_watchlist(account_id, content_type)

            if not any([favorites, rated_content, watchlist]):
                return None
                
            preferences = self._analyze_real_content_data(favorites, rated_content, watchlist, content_type, analysis_depth)
            return preferences
            
        except Exception as e:
            print(f"Error getting {content_type} preferences: {e}")
            return None

    def _get_user_favorites(self, account_id: int, content_type: str) -> List[Dict]:
        """Get user's favorite movies or TV shows."""
        endpoint = f"/account/{account_id}/favorite/{content_type}"
        params = {"session_id": self._session_token}

        data = self._make_api_request(endpoint, params)
        return data.get("results", []) if data else []

    def _get_user_rated_content(self, account_id: int, content_type: str) -> List[Dict]:
        """Get user's rated movies or TV shows."""
        endpoint = f"/account/{account_id}/rated/{content_type}"
        params = {"session_id": self._session_token}
        
        data = self._make_api_request(endpoint, params)
        return data.get("results", []) if data else []

    def _get_user_watchlist(self, account_id: int, content_type: str) -> List[Dict]:
        """Get user's watchlist movies or TV shows."""
        endpoint = f"/account/{account_id}/watchlist/{content_type}"
        params = {"session_id": self._session_token}
        
        data = self._make_api_request(endpoint, params)
        return data.get("results", []) if data else []

    def _analyze_real_content_data(self, favorites: List[Dict], rated_content: List[Dict], 
                                  watchlist: List[Dict], content_type: str, analysis_depth: str) -> Dict[str, Any]:
        """Analyze real content data to extract preferences for movies or TV shows."""
        # Merge all lists and deduplicate content based on TMDB ID
        all_items = favorites + rated_content + watchlist
        
        # Create a set of unique items based on TMDB ID
        unique_ids = set()
        all_content = []
        
        for item in all_items:
            tmdb_id = item.get("id")
            if tmdb_id and tmdb_id not in unique_ids:
                unique_ids.add(tmdb_id)
                all_content.append(item)
        
        if not all_content:
            return {"error": f"No {content_type} data to analyze"}
        
        date_field = "release_date" if content_type == "movies" else "first_air_date"
        content_name_field = "title" if content_type == "movies" else "name"
        
        genre_counts = {}
        rating_scores = []
        decade_counts = {}
        language_counts = {}
        
        for item in all_content:
            # Genre analysis
            for genre_id in item.get("genre_ids", []):
                genre_name = self._get_genre_name(genre_id, "movie" if content_type == "movies" else "tv")
                genre_counts[genre_name] = genre_counts.get(genre_name, 0) + 1
            
            # Rating analysis
            if "rating" in item:
                rating_scores.append(item["rating"])
            
            # Decade analysis
            date_value = item.get(date_field, "")
            if date_value and len(date_value) >= 4:
                try:
                    year = int(date_value[:4])
                    decade = f"{(year // 10) * 10}s"
                    decade_counts[decade] = decade_counts.get(decade, 0) + 1
                except ValueError:
                    pass
            
            # Language analysis
            original_language = item.get("original_language", "")
            if original_language:
                language_counts[original_language] = language_counts.get(original_language, 0) + 1
        
        # Calculate preferences
        total_items = len(all_content)
        favorite_genres = {genre: round(count/total_items, 2) for genre, count in genre_counts.items()}
        
        count_key = f"total_analyzed_{content_type.replace('movies', 'movies').replace('tv', 'shows')}"
        
        preferences = {
            "favorite_genres": dict(sorted(favorite_genres.items(), key=lambda x: x[1], reverse=True)),
            "rating_patterns": {
                "average_rating_given": round(sum(rating_scores) / len(rating_scores), 1) if rating_scores else None,
                "total_ratings": len(rating_scores),
                "minimum_threshold": min(rating_scores) if rating_scores else None,
                "maximum_rating": max(rating_scores) if rating_scores else None
            },
            "decade_preferences": dict(sorted(decade_counts.items(), key=lambda x: x[1], reverse=True)),
            "language_preferences": dict(sorted(language_counts.items(), key=lambda x: x[1], reverse=True)),
            count_key: total_items,
            "data_breakdown": {
                "favorites": len(favorites),
                "rated": len(rated_content),
                "watchlist": len(watchlist)
            }
        }
        
        if analysis_depth in ["detailed", "comprehensive"]:
            preferences.update(self._get_detailed_content_analysis(all_content, content_type))
        
        if analysis_depth == "comprehensive":
            preferences.update(self._get_comprehensive_content_analysis(all_content, content_type, content_name_field))
        
        return preferences

    def _get_detailed_content_analysis(self, content: List[Dict], content_type: str) -> Dict[str, Any]:
        """Get detailed content analysis for a higher depth level."""
        # Analyze popularity patterns
        popularity_scores = [item.get("popularity", 0) for item in content if item.get("popularity")]
        vote_averages = [item.get("vote_average", 0) for item in content if item.get("vote_average")]
        
        return {
            "popularity_preferences": {
                "average_popularity": round(sum(popularity_scores) / len(popularity_scores), 1) if popularity_scores else None,
                "prefers_mainstream": sum(1 for p in popularity_scores if p > 50) / len(popularity_scores) if popularity_scores else None
            },
            "quality_preferences": {
                "average_vote_preference": round(sum(vote_averages) / len(vote_averages), 1) if vote_averages else None,
                "high_quality_ratio": sum(1 for v in vote_averages if v >= 7.0) / len(vote_averages) if vote_averages else None
            }
        }

    def _get_comprehensive_content_analysis(self, content: List[Dict], content_type: str, content_name_field: str) -> Dict[str, Any]:
        """Get comprehensive content analysis for maximum depth."""
        comprehensive_data = {}
        
        # Add adult content analysis only for movies
        if content_type == "movies":
            adult_content = sum(1 for item in content if item.get("adult", False))
            comprehensive_data["content_maturity"] = {
                "adult_content_ratio": round(adult_content / len(content), 2) if content else 0,
                "family_friendly_preference": round((len(content) - adult_content) / len(content), 2) if content else 1
            }
        
        return comprehensive_data

    def _get_genre_name(self, genre_id: int, content_type: str) -> str:
        """Get genre names from genre IDs from TMDB API."""
        if content_type not in self._genre_cache:
            self._genre_cache[content_type] = self._fetch_genres(content_type)
        
        genre_map = self._genre_cache[content_type]
        return genre_map.get(genre_id, f"Unknown_Genre_{genre_id}")

    def _fetch_genres(self, content_type: str) -> Dict[int, str]:
        """Fetch genre mappings from TMDB API."""
        endpoint = f"/genre/{content_type}/list"
        data = self._make_api_request(endpoint)
        
        if data and "genres" in data:
            return {genre["id"]: genre["name"] for genre in data["genres"]}
        
        # Fallback genre mapping
        return {
            28: "Action", 12: "Adventure", 16: "Animation", 35: "Comedy", 80: "Crime",
            99: "Documentary", 18: "Drama", 10751: "Family", 14: "Fantasy", 36: "History",
            27: "Horror", 10402: "Music", 9648: "Mystery", 10749: "Romance", 878: "Science Fiction",
            10770: "TV Movie", 53: "Thriller", 10752: "War", 37: "Western",
            10759: "Action & Adventure", 10762: "Kids", 10763: "News", 10764: "Reality",
            10765: "Sci-Fi & Fantasy", 10766: "Soap", 10767: "Talk", 10768: "War & Politics"
        }

    def _generate_overall_insights(self, preferences: Dict[str, Any]) -> Dict[str, Any]:
        """Generate overall insights from movie and TV preferences."""
        insights = {
            "analysis_timestamp": datetime.now().isoformat(),
            "data_quality": "high_confidence_real_data"
        }
        
        # Determine primary content type
        movie_data = preferences.get("movie_preferences", {})
        tv_data = preferences.get("tv_preferences", {})
        
        if movie_data and tv_data:
            movie_count = movie_data.get("total_analyzed_movies", 0)
            tv_count = tv_data.get("total_analyzed_shows", 0)
            
            if movie_count > tv_count * 1.5:
                insights["primary_content_type"] = "movies"
            elif tv_count > movie_count * 1.5:
                insights["primary_content_type"] = "tv_shows"
            else:
                insights["primary_content_type"] = "balanced"
        elif movie_data:
            insights["primary_content_type"] = "movies"
        elif tv_data:
            insights["primary_content_type"] = "tv_shows"
        else:
            insights["primary_content_type"] = "unknown"
        
        # Quality threshold analysis
        movie_ratings = movie_data.get("rating_patterns", {})
        tv_ratings = tv_data.get("rating_patterns", {})
        
        all_ratings = []
        if movie_ratings.get("average_rating_given"):
            all_ratings.append(movie_ratings["average_rating_given"])
        if tv_ratings.get("average_rating_given"):
            all_ratings.append(tv_ratings["average_rating_given"])
        
        if all_ratings:
            insights["quality_threshold"] = round(sum(all_ratings) / len(all_ratings), 1)
        else:
            insights["quality_threshold"] = "no_rating_data"
        
        return insights

    def _calculate_confidence_score(self, preferences: Dict[str, Any]) -> float:
        """Calculate confidence score based on the available data."""
        movie_data = preferences.get("movie_preferences", {})
        tv_data = preferences.get("tv_preferences", {})
        
        # Base confidence on amount of data
        movie_count = movie_data.get("total_analyzed_movies", 0) if isinstance(movie_data, dict) else 0
        tv_count = tv_data.get("total_analyzed_shows", 0) if isinstance(tv_data, dict) else 0
        
        total_items = movie_count + tv_count
        
        if total_items == 0:
            return 0.0
        elif total_items < 5:
            confidence = 0.3
        elif total_items < 15:
            confidence = 0.6
        elif total_items < 50:
            confidence = 0.8
        else:
            confidence = 0.95
        
        movie_ratings = movie_data.get("rating_patterns", {}).get("total_ratings", 0) if isinstance(movie_data, dict) else 0
        tv_ratings = tv_data.get("rating_patterns", {}).get("total_ratings", 0) if isinstance(tv_data, dict) else 0
        
        if movie_ratings + tv_ratings > 0:
            confidence = min(1.0, confidence + 0.1)
        
        return round(confidence, 2)
