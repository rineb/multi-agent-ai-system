import json
import os
from typing import Type, Dict, List, Optional
from datetime import datetime
import random

from crewai.tools import BaseTool
import requests
from pydantic import BaseModel, Field


class TMDBToolInput(BaseModel):
    """Input schema for TMDB Tool (single run fetches both movies and TV)."""
    tmdb_content_type_max_result: int = Field(default=20, description="Maximum number of results.")
    min_rating: float = Field(default=6.0, description="Minimum rating filter")
    fetch_detailed_info: bool = Field(default=True, description="Fetch detailed info including actual runtime (makes additional API calls)")
           
class TmdbContentSearchTool(BaseTool):
    name: str = "TMDB Content Discovery Tool"
    description: str = "Discover popular movies and TV shows using TMDB API with actual runtime, ratings, and comprehensive metadata."
    args_schema: Type[BaseModel] = TMDBToolInput
    
    def __init__(self):
        super().__init__()
        self._api_key = os.environ.get("TMDB_API_KEY")
        self._genre_cache = {}  # In-memory cache for genres during run

    def _run(self, tmdb_content_type_max_result: int = 50, min_rating: float = 6.0, fetch_detailed_info: bool = True) -> str:
        """Discover popular movies and TV shows in a single run and return a combined JSON."""
        try:
            if not self._api_key:
                return json.dumps({"error": "TMDB_API_KEY not set", "movies": [], "tv_shows": []})

            movies = self._get_movies(tmdb_content_type_max_result, min_rating, fetch_detailed_info)
            tv_shows = self._get_tv_shows(tmdb_content_type_max_result, min_rating, fetch_detailed_info)

            return json.dumps({
                "movies": movies,
                "tv_shows": tv_shows,
                "total_movies": len(movies),
                "total_tv_shows": len(tv_shows)
            }, indent=2)
        except Exception as e:
            return json.dumps({"error": f"Error fetching content: {str(e)}", "movies": [], "tv_shows": []})

    def _get_movies(self, tmdb_content_type_max_result: int, min_rating: float, fetch_detailed_info: bool) -> list:
        """Get popular movies with page mixing and optional discovery for diversity."""
        rng = self._get_seeded_random_number_generator()

        # Primary page: Always take content from page 1 for highest popularity
        primary_items = self._fetch_popular_movies_page(page=1, min_rating=min_rating)

        # Secondary pages: choose from popularity pages 2-5
        secondary_pages = rng.sample(range(2, 11), k=2)  # choose up to 2 pages for variety
        secondary_items: List[Dict] = []
        for page in secondary_pages:
            secondary_items.extend(self._fetch_popular_movies_page(page=page, min_rating=min_rating))

        discover_page = rng.choice(range(2, 6))
        discover_items = self._fetch_discover_movies_page(page=discover_page, min_rating=min_rating)

        # Deduplicate by <tmdb_id> and shuffle
        combined_content: List[Dict] = []
        unique_items = set()
        for bucket in [primary_items, secondary_items, discover_items]:
            for item in bucket:
                tmdb_id = item.get("tmdb_id")
                if tmdb_id and tmdb_id not in unique_items:
                    unique_items.add(tmdb_id)
                    combined_content.append(item)

        random.shuffle(combined_content)

        results: List[Dict] = []
        for item in combined_content:
            if fetch_detailed_info and item.get("runtime_minutes") is None and item.get("tmdb_id"):
                details = self._get_movie_details(item["tmdb_id"])
                item["runtime_minutes"] = details.get("runtime", None)
                item["tagline"] = details.get("tagline", "")
            results.append(item)

            if len(results) >= tmdb_content_type_max_result:
                break

        return results

    def _get_tv_shows(self, tmdb_content_type_max_result: int, min_rating: float, fetch_detailed_info: bool) -> list:
        """Get popular TV shows with page mixing and optional discovery for diversity."""
        rng = self._get_seeded_random_number_generator()

        # Primary page: Always take content from page 1 for highest popularity
        primary_items = self._fetch_popular_tv_page(page=1, min_rating=min_rating)

        # Secondary pages: choose from popularity pages 2-5
        secondary_pages = rng.sample(range(2, 11), k=2)
        secondary_items: List[Dict] = []
        for page in secondary_pages:
            secondary_items.extend(
                self._fetch_popular_tv_page(page=page, min_rating=min_rating))

        discover_page = rng.choice(range(2, 5))
        discover_items = self._fetch_discover_tv_page(page=discover_page, min_rating=min_rating)

        # Deduplicate by <tmdb_id> and shuffle
        combined_content: List[Dict] = []
        unique_items = set()
        for bucket in [primary_items, secondary_items, discover_items]:
            for item in bucket:
                tmdb_id = item.get("tmdb_id")
                if tmdb_id and tmdb_id not in unique_items:
                    unique_items.add(tmdb_id)
                    combined_content.append(item)

        random.shuffle(combined_content)

        results: List[Dict] = []
        for item in combined_content:
            if fetch_detailed_info and item.get("tmdb_id"):
                details = self._get_tv_show_details(item["tmdb_id"])
                item.update({
                    "episode_runtime_minutes": self._get_average_episode_runtime(details.get("episode_run_time")),
                    "number_of_seasons": details.get("number_of_seasons", item.get("number_of_seasons")),
                    "number_of_episodes": details.get("number_of_episodes", item.get("number_of_episodes")),
                    "status": details.get("status", item.get("status", "Unknown")),
                    "networks": [n.get("name", "") for n in details.get("networks", [])],
                    "created_by": [c.get("name", "") for c in details.get("created_by", [])]
                })
            results.append(item)

            if len(results) >= tmdb_content_type_max_result:
                break

        return results

    def _fetch_popular_movies_page(self, page: int, min_rating: float) -> List[Dict]:
        endpoint = "/movie/popular"
        params = {"include_adult": False, "page": page}
        data = self._make_api_request(endpoint, params)

        if not data:
            return []

        items: List[Dict] = []
        for movie in data.get("results", []):
            if movie.get("vote_average", 0) >= min_rating:
                items.append({
                    "tmdb_id": movie.get("id"),
                    "title": movie.get("title", "N/A"),
                    "content_type": "movie",
                    "url": f"https://www.themoviedb.org/movie/{movie.get('id')}" if movie.get("id") else None,
                    "genres": self._get_genre_names(movie.get("genre_ids", []), "movie"),
                    "release_date": movie.get("release_date", "N/A"),
                    "overview": movie.get("overview", "N/A"),
                    "vote_average": movie.get("vote_average", 0),
                    "vote_count": movie.get("vote_count", 0),
                })

        return items

    def _fetch_discover_movies_page(self, page: int, min_rating: float) -> List[Dict]:
        endpoint = "/discover/movie"
        params = {
            "include_adult": False,
            "page": page,
            "sort_by": "vote_average.desc",
            "vote_count.gte": 2000
        }
        data = self._make_api_request(endpoint, params)
        if not data:
            return []

        items: List[Dict] = []
        for movie in data.get("results", []):
            if movie.get("vote_average", 0) >= min_rating:
                items.append({
                    "tmdb_id": movie.get("id"),
                    "title": movie.get("title", "N/A"),
                    "content_type": "movie",
                    "url": f"https://www.themoviedb.org/movie/{movie.get('id')}" if movie.get("id") else None,
                    "genres": self._get_genre_names(movie.get("genre_ids", []), "movie"),
                    "release_date": movie.get("release_date", "N/A"),
                    "overview": movie.get("overview", "N/A"),
                    "vote_average": movie.get("vote_average", 0),
                    "vote_count": movie.get("vote_count", 0),
                })

        return items

    def _fetch_popular_tv_page(self, page: int, min_rating: float) -> List[Dict]:
        endpoint = "/tv/popular"
        params = {"include_adult": False, "page": page}
        data = self._make_api_request(endpoint, params)
        if not data:
            return []
        items: List[Dict] = []
        for show in data.get("results", []):
            if show.get("vote_average", 0) >= min_rating:
                items.append({
                    "tmdb_id": show.get("id"),
                    "title": show.get("name", "N/A"),
                    "content_type": "tv",
                    "url": f"https://www.themoviedb.org/tv/{show.get('id')}" if show.get("id") else None,
                    "genres": self._get_genre_names(show.get("genre_ids", []), "tv"),
                    "first_air_date": show.get("first_air_date", "N/A"),
                    "overview": show.get("overview", "N/A"),
                    "vote_average": show.get("vote_average", 0),
                    "vote_count": show.get("vote_count", 0),
                })

        return items

    def _fetch_discover_tv_page(self, page: int, min_rating: float) -> List[Dict]:
        endpoint = "/discover/tv"
        params = {
            "include_adult": False,
            "page": page,
            "sort_by": "vote_average.desc",
            "vote_count.gte": 200
        }
        data = self._make_api_request(endpoint, params)
        if not data:
            return []
        items: List[Dict] = []
        for show in data.get("results", []):
            if show.get("vote_average", 0) >= min_rating:
                items.append({
                    "tmdb_id": show.get("id"),
                    "title": show.get("name", "N/A"),
                    "content_type": "tv",
                    "url": f"https://www.themoviedb.org/tv/{show.get('id')}" if show.get("id") else None,
                    "genres": self._get_genre_names(show.get("genre_ids", []), "tv"),
                    "first_air_date": show.get("first_air_date", "N/A"),
                    "overview": show.get("overview", "N/A"),
                    "vote_average": show.get("vote_average", 0),
                    "vote_count": show.get("vote_count", 0),
                })

        return items

    def _get_movie_details(self, movie_id: int) -> dict:
        """Get detailed movie information including runtime."""
        endpoint = f"/movie/{movie_id}"
        data = self._make_api_request(endpoint)

        if data:
            return data
        else:
            return {"runtime": None}

    def _get_tv_show_details(self, tv_id: int) -> dict:
        """Get detailed TV show information including episode runtime."""
        endpoint = f"/tv/{tv_id}"
        data = self._make_api_request(endpoint)

        if data:
            return data
        else:
            return {
                "episode_run_time": None,
                "number_of_seasons": None,
                "number_of_episodes": None,
                "status": None
            }

    def _get_average_episode_runtime(self, episode_run_times: list) -> int:
        """Calculate average episode runtime from list of runtimes."""
        if not episode_run_times:
            return 45  # Default fallback

        return int(sum(episode_run_times) / len(episode_run_times))

    def _make_api_request(self, endpoint: str, params: Dict = None) -> Optional[Dict]:
        """Make an API request to TMDB."""
        try:
            url = f"{'https://api.themoviedb.org/3'}{endpoint}"
            default_params = {"api_key": self._api_key}
            if params:
                default_params.update(params)

            response = requests.get(url, params=default_params, timeout=15)
            response.raise_for_status()
            data = response.json()
            
            return data
        except requests.exceptions.RequestException as e:
            print(f"TMDB API request failed for {endpoint}: {e}")
            return None
        except Exception as e:
            print(f"Unexpected error in TMDB API request: {e}")
            return None

    def _get_seeded_random_number_generator(self) -> random.Random:
        """Create a deterministic random number generator (RNG) per day to cycle pages across runs."""
        seed = int(datetime.now().strftime("%Y%m%d"))
        return random.Random(seed)

    def _fetch_genres(self, content_type: str) -> Dict[int, str]:
        """Fetch genre mappings from TMDB API."""
        endpoint = f"/genre/{content_type}/list"
        data = self._make_api_request(endpoint)
        
        if data and "genres" in data:
            return {genre["id"]: genre["name"] for genre in data["genres"]}
        
        return self._get_fallback_genres()

    def _get_genre_names(self, genre_ids: List[int], content_type: str) -> List[str]:
        """Get genre names from genre IDs from TMDB API."""
        if content_type not in self._genre_cache:
            self._genre_cache[content_type] = self._fetch_genres(content_type)
        
        genre_map = self._genre_cache[content_type]
        return [genre_map.get(genre_id, f"Unknown_Genre_{genre_id}") for genre_id in genre_ids]

    def _get_fallback_genres(self) -> Dict[int, str]:
        """Fallback genre mapping if TMDB API is unavailable."""
        return {
            28: "Action", 12: "Adventure", 16: "Animation", 35: "Comedy", 80: "Crime",
            99: "Documentary", 18: "Drama", 10751: "Family", 14: "Fantasy", 36: "History",
            27: "Horror", 10402: "Music", 9648: "Mystery", 10749: "Romance", 878: "Science Fiction",
            10770: "TV Movie", 53: "Thriller", 10752: "War", 37: "Western",
            10759: "Action & Adventure", 10762: "Kids", 10763: "News", 10764: "Reality",
            10765: "Sci-Fi & Fantasy", 10766: "Soap", 10767: "Talk", 10768: "War & Politics"
        }
