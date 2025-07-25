import os
import requests
from typing import Type
from crewai.tools import BaseTool
from pydantic import BaseModel, Field


class DiscordDeliveryInput(BaseModel):
    """Input schema for Discord Delivery Tool"""
    content: str = Field(..., description="Content to send to Discord channel")


class DiscordDeliveryTool(BaseTool):
    name: str = "Discord Delivery Tool"
    description: str = "Send content to Discord channel"
    args_schema: Type[BaseModel] = DiscordDeliveryInput
    
    def _run(self, content: str) -> str:
        print('Discord Tool is being used')
        """Send content to Discord using Discord REST API."""
        
        # Get bot token and channel ID from environment
        bot_token = os.getenv('DISCORD_BOT_TOKEN')
        channel_id = os.getenv('DISCORD_CHANNEL_ID')
        
        if not bot_token:
            return "ERROR: DISCORD_BOT_TOKEN environment variable not set"
        
        if not channel_id:
            return "ERROR: DISCORD_CHANNEL_ID environment variable not set"
        
        # Basic length check
        if len(content) > 2000:
            content = content[:1950] + "\n...[truncated]"
        
        try:
            # Direct Discord API call - simple HTTP POST
            url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
            headers = {
                "Authorization": f"Bot {bot_token}",
                "Content-Type": "application/json"
            }
            payload = {
                "content": content,
                "flags": 4  # Supress link embeds / previews
            }
            
            response = requests.post(url, headers=headers, json=payload, timeout=15)
            
            if response.status_code == 200 or response.status_code == 201:
                message_data = response.json()
                message_id = message_data.get('id')
                
                if message_id:
                    self._add_feedback_reactions(bot_token, channel_id, message_id)
                
                return "Message sent to Discord successfully!"
            elif response.status_code == 403:
                return "Permission denied: Bot lacks Send Messages permission in this channel"
            elif response.status_code == 404:
                return "Channel not found: Check DISCORD_CHANNEL_ID"
            else:
                error_msg = f"Discord API error: {response.status_code} - {response.text}"
                return error_msg
                
        except requests.exceptions.RequestException as e:
            error_msg = f"Request failed: {str(e)}"
            return error_msg

    def _add_feedback_reactions(self, bot_token: str, channel_id: str, message_id: str) -> None:
        """Add placeholder reaction emojis to the sent message for feedback collection."""
        feedback_emojis = ["👍", "👎", "✅", "❌", "⭐", "🕐"]
        headers = {"Authorization": f"Bot {bot_token}"}
        
        for emoji in feedback_emojis:
            try:
                url = f"https://discord.com/api/v10/channels/{channel_id}/messages/{message_id}/reactions/{emoji}/@me"
                requests.put(url, headers=headers, timeout=5)
            except Exception:
                # Don't fail the whole message delivery if reactions fail
                continue
