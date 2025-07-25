#!/usr/bin/env python
import os
import sys
import warnings

from datetime import datetime

from multi_agent_system.crew import MultiAgentSystem

warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")

# This main file is intended to be a way for you to run your
# crew locally, so refrain from adding unnecessary logic into this file.
# Replace with inputs you want to test with, it will automatically
# interpolate any tasks and agents information

def run():
    """
    Run the crew.
    """
    inputs = {
        # Calendar Analysis Parameters
        'calendar_id': os.getenv('GOOGLE_CALENDAR_ID'),
        'start_date': datetime.today().date().strftime('%Y-%m-%d'),
        'end_date': datetime.today().date().strftime('%Y-%m-%d'),
        'timezone': 'Europe/Berlin',
        'min_free_time_minutes': 10,
        
        # User Preference Parameters
        'user_id': os.getenv('TMDB_USER_ID'),
        
        # Recommendation Parameters
        'tmdb_content_type_max_result': 20,
        'top_final_recommendations': 6,
        'max_episode_candidates': 30,
        'format_example': """\
            🎯 Today's Top Picks

            CRITICAL EMOJI ASSIGNMENT RULES - MUST FOLLOW EXACTLY:
            - Use 🎬 ONLY for movies (content_type="movie" OR URLs containing "themoviedb.org/movie/")
            - Use 📺 ONLY for TV shows (content_type="tv" OR URLs containing "themoviedb.org/tv/")  
            - Use 🎧 ONLY for podcasts (content from Spotify or audio platforms, NOT movies/TV)
            
            NEVER mix up emojis - a movie must ALWAYS use 🎬, TV shows must ALWAYS use 📺
            
            URL PRESERVATION RULES:
            - Use the exact URL from the data - do NOT modify, reconstruct, or change it
            - If URL is missing or null, show title without link: "Title Name (No URL)"
            - NEVER guess URLs from titles or IDs

            EXAMPLES:
             - 🎬 [Movie Title](https://www.themoviedb.org/movie/12345) — Drama, Action — 8.5/10
            🕒 14:00 (2h 15m) — Perfect drama for afternoon viewing based on your preferences

            - 📺 [TV Show Name](https://www.themoviedb.org/tv/67890) — Comedy, Drama — 9.1/10
            🕒 20:00 (45m episode) — Great evening entertainment matching your taste

            - 🎧 [Podcast Name](https://spotify.com/episode/xyz) — Technology — ~45m
            🕒 10:00 (45m) — Informative tech content for morning listening
        """,
    }
    
    try:
        MultiAgentSystem().crew().kickoff(inputs=inputs)

    except Exception as e:
        raise Exception(f"An error occurred while running the crew: {e}")
