import os

from crewai import Agent, Crew, Process, Task, LLM
from crewai.project import CrewBase, agent, crew, task, llm
from crewai.agents.agent_builder.base_agent import BaseAgent
from typing import List

from src.multi_agent_system.tools.discord_delivery_tool import DiscordDeliveryTool
from src.multi_agent_system.tools.discord_feedback_tool import DiscordFeedbackTool
from src.multi_agent_system.tools.google_calendar_busy_periods_tool import GoogleCalendarBusyPeriodsTool
from src.multi_agent_system.tools.tmdb_content_search_tool import TmdbContentSearchTool
from src.multi_agent_system.tools.tmdb_user_preference_tool import TMDBUserPreferenceTool
from src.multi_agent_system.tools.spotify_user_preference_tool import SpotifyUserPreferenceTool

# If you want to run a snippet of code before or after the crew starts,
# you can use the @before_kickoff and @after_kickoff decorators
# https://docs.crewai.com/concepts/crews#example-crew-class-with-decorators

@CrewBase
class MultiAgentSystem():
    """MultiAgentSystem crew"""

    agents: List[BaseAgent]
    tasks: List[Task]

    # Learn more about YAML configuration files here:
    # Agents: https://docs.crewai.com/concepts/agents#yaml-configuration-recommended
    # Tasks: https://docs.crewai.com/concepts/tasks#yaml-configuration-recommended
    
    # If you would like to add tools to your agents, you can learn more about it here:
    # https://docs.crewai.com/concepts/agents#agent-tools
    
    @agent
    def calendar_time_slot_analyzer(self) -> Agent:
        return Agent(
            config=self.agents_config['calendar_time_slot_analyzer'], # type: ignore[index]
            tools=[GoogleCalendarBusyPeriodsTool()],
            allow_delegation=False,
            verbose=True
        )

    @agent
    def tmdb_content_searcher(self) -> Agent:
        return Agent(
            config=self.agents_config['tmdb_content_searcher'], # type: ignore[index]
            tools=[TmdbContentSearchTool()],
            allow_delegation=False,
            verbose=True
        )

    @agent
    def tmdb_user_preference_analyzer(self) -> Agent:
        return Agent(
            config=self.agents_config['tmdb_user_preference_analyzer'], # type: ignore[index]
            tools=[TMDBUserPreferenceTool()],
            allow_delegation=False,
            verbose=True
        )

    @agent
    def spotify_podcast_preference_analyzer(self) -> Agent:
        return Agent(
            config=self.agents_config['spotify_podcast_preference_analyzer'], # type: ignore[index]
            tools=[SpotifyUserPreferenceTool()],
            allow_delegation=False,
            verbose=True
        )

    @agent
    def content_recommendation_synthesizer(self) -> Agent:
        return Agent(
            config=self.agents_config['content_recommendation_synthesizer'], # type: ignore[index]
            tools=[],  # Selection/reasoning only; link validation happens in formatter
            allow_delegation=False,
            verbose=True
        )

    @agent
    def discord_message_formatter(self) -> Agent:
        return Agent(
            config=self.agents_config['discord_message_formatter'], # type: ignore[index]
            tools=[],
            allow_delegation=False,
            verbose=True
        )

    @agent
    def discord_feedback_collector(self) -> Agent:
        return Agent(
            config=self.agents_config['discord_feedback_collector'], # type: ignore[index]
            tools=[DiscordFeedbackTool()],
            allow_delegation=False,
            verbose=True
        )

    @agent
    def discord_delivery_specialist(self) -> Agent:
        return Agent(
            config=self.agents_config['discord_delivery_specialist'], # type: ignore[index]
            tools=[DiscordDeliveryTool()],
            allow_delegation=False,
            verbose=True
        )

    # To learn more about structured task outputs,
    # task dependencies, and task callbacks, check out the documentation:
    # https://docs.crewai.com/concepts/tasks#overview-of-a-task
    
    @task
    def analyze_calendar_time_slots_task(self) -> Task:
        return Task(
            config=self.tasks_config['analyze_calendar_time_slots_task'], # type: ignore[index]
            # No context - can run in parallel with other fetch tasks
            output_file='task_output/analyze_calendar_time_slots.json',
        )

    @task
    def search_tmdb_content_task(self) -> Task:
        return Task(
            config=self.tasks_config['search_tmdb_content_task'], # type: ignore[index]
            # No context - can run in parallel with other fetch tasks
            output_file='task_output/search_tmdb_content.json',
        )

    @task
    def analyze_user_tmdb_preferences_task(self) -> Task:
        return Task(
            config=self.tasks_config['analyze_user_tmdb_preferences_task'], # type: ignore[index]
            # No context - can run in parallel with other fetch tasks
            output_file='task_output/analyze_user_tmdb_preferences.json',
        )

    @task
    def analyze_user_spotify_preferences_task(self) -> Task:
        return Task(
            config=self.tasks_config['analyze_user_spotify_preferences_task'], # type: ignore[index]
            # No context - can run in parallel with other fetch tasks
            output_file='task_output/analyze_user_spotify_preferences.json',
        )

    @task
    def collect_discord_feedback_task(self) -> Task:
        return Task(
            config=self.tasks_config['collect_discord_feedback_task'], # type: ignore[index]
            # No context - can run in parallel with other fetch tasks
            output_file='task_output/collect_discord_feedback.json',
        )

    @task
    def synthesize_content_recommendations_task(self) -> Task:
        return Task(
            config=self.tasks_config['synthesize_content_recommendations_task'], # type: ignore[index]
            context=[
                self.analyze_calendar_time_slots_task(),
                self.search_tmdb_content_task(),
                self.analyze_user_tmdb_preferences_task(),
                self.analyze_user_spotify_preferences_task(),
                self.collect_discord_feedback_task()
            ],
            output_file='task_output/synthesize_content_recommendations.json',
        )

    @task
    def format_recommendations_task(self) -> Task:
        return Task(
            config=self.tasks_config['format_recommendations_task'], # type: ignore[index]
            agent=self.discord_message_formatter(),
            context=[self.synthesize_content_recommendations_task()],
            output_file='task_output/format_recommendations.md',
        )

    @task
    def discord_delivery_task(self) -> Task:
        return Task(
            config=self.tasks_config['discord_delivery_task'], # type: ignore[index]
            agent=self.discord_delivery_specialist(),
            context=[self.format_recommendations_task()],
            output_file='task_output/discord_delivery.md',
        )

    @llm
    def openai_gpt_5o(self) -> LLM:
        return LLM(
            model=os.getenv('OPENAI_MODEL')
        )

    @crew
    def crew(self) -> Crew:
        """Creates the MultiAgentSystem crew"""
        # To learn how to add knowledge sources to your crew, check out the documentation:
        # https://docs.crewai.com/concepts/knowledge#what-is-knowledge

        return Crew(
            agents=self.agents, # Automatically created by the @agent decorator
            tasks=self.tasks, # Automatically created by the @task decorator
            process=Process.sequential,
            chat_llm=self.openai_gpt_5o,
            verbose=True,
            cache=False
        )
