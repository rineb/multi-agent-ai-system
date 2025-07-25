import os
import json
import requests
from datetime import datetime, timedelta
from typing import Type, Dict, List, Optional
from crewai.tools import BaseTool
from pydantic import BaseModel, Field


class DiscordFeedbackInput(BaseModel):
    """Input schema for Discord Feedback Collection Tool"""
    days_back: int = Field(default=7, description="Number of days back to check for messages with feedback")
    reaction_emojis: List[str] = Field(
        default=["👍", "👎", "✅", "❌", "⭐", "🕐"], 
        description="List of emoji reactions to analyze for feedback"
    )


class DiscordFeedbackTool(BaseTool):
    name: str = "Discord Feedback Collection Tool"
    description: str = "Collect and analyze emoji reactions from the bot's previous messages in the Discord channel to understand user feedback patterns"
    args_schema: Type[BaseModel] = DiscordFeedbackInput
    
    def _run(self, days_back: int = 7, reaction_emojis: List[str] = None) -> str:
        """Collect feedback from Discord channel by analyzing reactions on the bot's messages."""
        
        bot_token = os.getenv('DISCORD_BOT_TOKEN')
        channel_id = os.getenv('DISCORD_CHANNEL_ID')
        
        if not bot_token:
            return json.dumps({"error": "DISCORD_BOT_TOKEN environment variable not set", "feedback": []})
        
        if not channel_id:
            return json.dumps({"error": "DISCORD_CHANNEL_ID environment variable not set", "feedback": []})
        
        try:
            bot_user_id = self._get_bot_user_id(bot_token)
            if not bot_user_id:
                return json.dumps({"error": "Failed to retrieve bot user ID", "feedback": []})
            
            messages = self._get_recent_messages(bot_token, channel_id, days_back)
            if not messages:
                return json.dumps({
                    "message": "No recent messages found in channel", 
                    "feedback": [],
                    "days_checked": days_back
                })
            
            # Filter messages sent by the bot
            bot_messages = [msg for msg in messages if msg.get('author', {}).get('id') == bot_user_id]
            
            if not bot_messages:
                return json.dumps({
                    "message": "No messages sent by bot found in recent history", 
                    "feedback": [],
                    "days_checked": days_back,
                    "total_messages_checked": len(messages)
                })
            
            feedback_data = self._collect_message_feedback(bot_messages, reaction_emojis)
            
            feedback_summary = self._analyze_feedback_patterns(feedback_data)
            
            return json.dumps({
                "feedback_collection_summary": {
                    "days_analyzed": days_back,
                    "bot_messages_found": len(bot_messages),
                    "messages_with_reactions": len([msg for msg in feedback_data if sum(msg["reactions"].values()) > 0]),
                    "total_reactions_collected": sum(sum(msg["reactions"].values()) for msg in feedback_data)
                },
                "detailed_feedback": feedback_data,
                "feedback_patterns": feedback_summary
            }, indent=2, ensure_ascii=False)
            
        except Exception as e:
            return json.dumps({
                "error": f"Error collecting Discord feedback: {str(e)}", 
                "feedback": []
            })
    
    def _get_bot_user_id(self, bot_token: str) -> Optional[str]:
        """Get the bot's user ID using the Discord API."""
        try:
            url = "https://discord.com/api/v10/users/@me"
            headers = {"Authorization": f"Bot {bot_token}"}
            
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            
            user_data = response.json()
            return user_data.get('id')
            
        except Exception as e:
            print(f"Error getting bot user ID: {e}")
            return None
    
    def _get_recent_messages(self, bot_token: str, channel_id: str, days_back: int) -> List[Dict]:
        """Get recent messages from the Discord channel."""
        try:
            cutoff_date = datetime.now() - timedelta(days=days_back)
            
            url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
            headers = {"Authorization": f"Bot {bot_token}"}
            params = {"limit": 100}  # Discord API limit
            
            response = requests.get(url, headers=headers, params=params, timeout=15)
            response.raise_for_status()
            
            messages = response.json()
            
            # Filter messages by date
            recent_messages = []
            for message in messages:
                message_date = datetime.fromisoformat(message['timestamp'].replace('Z', '+00:00'))
                if message_date.replace(tzinfo=None) >= cutoff_date:
                    recent_messages.append(message)
            
            return recent_messages
            
        except Exception as e:
            print(f"Error getting recent messages: {e}")
            return []
    
    def _collect_message_feedback(self, bot_messages: List[Dict], reaction_emojis: List[str]) -> List[Dict]:
        """Collect reaction feedback from bot messages that have reactions."""
        feedback_data = []
        
        # The bot_messages already contain reaction data from the /messages endpoint
        for message in bot_messages:
            message_id = message['id']
            message_content = message.get('content', None)
            message_timestamp = message['timestamp']
            
            # Extract reactions directly from the message object
            reactions = self._extract_reactions_from_message(message, reaction_emojis)
            
            # Only include messages that have actual reactions (non-zero reaction counts)
            if sum(reactions.values()) > 0:
                feedback_data.append({
                    "message_id": message_id,
                    "message_content": message_content,
                    "timestamp": message_timestamp,
                    "reactions": reactions
                })
        
        return feedback_data
    
    def _extract_reactions_from_message(self, message: Dict, reaction_emojis: List[str]) -> Dict[str, int]:
        """Extract reaction counts from a message object, excluding bot's own reactions."""
        reactions = {}
        message_id = message.get('id', 'unknown')
        
        try:
            message_reactions = message.get('reactions', [])
            
            # Initialize all emojis to 0
            for emoji in reaction_emojis:
                reactions[emoji] = 0
            
            # Process each reaction from the message
            for reaction in message_reactions:
                emoji_data = reaction.get('emoji', {})
                emoji_name = emoji_data.get('name', '')
                count = reaction.get('count', 0)
                me = reaction.get('me', False)  # Whether the bot reacted
                
                # Check if this emoji is one we're tracking
                if emoji_name in reaction_emojis:
                    # Subtract 1 if the bot reacted to exclude the bot's reaction
                    human_count = count - (1 if me else 0)
                    reactions[emoji_name] = max(0, human_count)  # Ensure non-negative

            return reactions
            
        except Exception as e:
            print(f"Error extracting reactions from message {message_id}: {e}")
            # Return zero counts for all emojis
            return {emoji: 0 for emoji in reaction_emojis}
    
    def _analyze_feedback_patterns(self, feedback_data: List[Dict]) -> Dict:
        """Analyze feedback patterns to provide insights for content recommendations."""
        
        # Aggregate reaction totals
        total_reactions = {"👍": 0, "👎": 0, "✅": 0, "❌": 0, "⭐": 0, "🕐": 0}
        messages_with_feedback = 0
        
        for message_feedback in feedback_data:
            reactions = message_feedback["reactions"]
            if sum(reactions.values()) > 0:
                messages_with_feedback += 1
            
            for emoji, count in reactions.items():
                if emoji in total_reactions:
                    total_reactions[emoji] += count
        
        # Calculate feedback metrics
        total_feedback = sum(total_reactions.values())
        
        if total_feedback == 0:
            return {
                "overall_satisfaction": "no_feedback",
                "engagement_level": "no_engagement",
                "content_preferences": {},
                "timing_feedback": {},
                "recommendations": ["No feedback collected yet. Encourage users to react to recommendations."]
            }
        
        # Analyze satisfaction
        positive_reactions = total_reactions["👍"] + total_reactions["✅"] + total_reactions["⭐"]
        negative_reactions = total_reactions["👎"] + total_reactions["❌"]
        satisfaction_score = positive_reactions / (positive_reactions + negative_reactions) if (positive_reactions + negative_reactions) > 0 else 0.5
        
        # Analyze engagement
        consumption_rate = total_reactions["✅"] / total_feedback if total_feedback > 0 else 0
        
        # Analyze timing feedback
        timing_issues = total_reactions["🕐"] / total_feedback if total_feedback > 0 else 0
        
        return {
            "overall_satisfaction": self._categorize_satisfaction(satisfaction_score),
            "satisfaction_score": round(satisfaction_score, 2),
            "engagement_level": self._categorize_engagement(consumption_rate),
            "consumption_rate": round(consumption_rate, 2),
            "content_preferences": {
                "liked_content": total_reactions["👍"],
                "disliked_content": total_reactions["👎"],
                "perfect_matches": total_reactions["⭐"],
                "actually_consumed": total_reactions["✅"],
                "not_interested": total_reactions["❌"]
            },
            "timing_feedback": {
                "timing_issues": total_reactions["🕐"],
                "timing_issue_rate": round(timing_issues, 2)
            },
            "total_feedback_points": total_feedback,
            "messages_with_feedback": messages_with_feedback,
            "recommendations": self._generate_recommendations(satisfaction_score, consumption_rate, timing_issues)
        }
    
    def _categorize_satisfaction(self, score: float) -> str:
        """Categorize satisfaction score."""
        if score >= 0.8:
            return "high"
        elif score >= 0.6:
            return "moderate"
        elif score >= 0.4:
            return "low"
        else:
            return "very_low"
    
    def _categorize_engagement(self, rate: float) -> str:
        """Categorize engagement/consumption rate."""
        if rate >= 0.7:
            return "high"
        elif rate >= 0.4:
            return "moderate"
        else:
            return "low"
    
    def _generate_recommendations(self, satisfaction_score: float, consumption_rate: float, timing_issues: float) -> List[str]:
        """Generate recommendations for improving content recommendations."""
        recommendations = []
        
        if satisfaction_score < 0.6:
            recommendations.append("Consider adjusting genre preferences, current content may not match user tastes")
        
        if consumption_rate < 0.4:
            recommendations.append("Users are interested but not consuming content, check time slot accuracy and content accessibility")
        
        if timing_issues > 0.2:
            recommendations.append("Significant timing feedback detected, review time slot assignments and content duration matching")
        
        if satisfaction_score >= 0.8 and consumption_rate >= 0.6:
            recommendations.append("Great feedback patterns! Current recommendation strategy is working well")
        
        if not recommendations:
            recommendations.append("Feedback patterns are moderate, continue monitoring and fine-tuning recommendations")
        
        return recommendations
