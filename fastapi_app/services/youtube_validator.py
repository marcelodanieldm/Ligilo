"""
YouTube Video Validator Service
================================
Sprint 3: Validates YouTube submissions for scout videos.

Requirements:
1. Privacy: Must not be "Private" (only "Unlisted" or "Public")
2. Duration: Between 60-180 seconds
3. Tags/Title: Must contain #LigiloScout or patrol name
4. Metadata: Extract embed_url for Dashboard viewing
"""
import os
import re
from typing import Optional
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


# Initialize YouTube API client
_youtube_client = None


def _get_youtube_client():
    """Lazy initialization of YouTube API client."""
    global _youtube_client
    if _youtube_client is None:
        api_key = os.getenv("YOUTUBE_API_KEY")
        if not api_key:
            raise ValueError("YOUTUBE_API_KEY environment variable not set")
        _youtube_client = build("youtube", "v3", developerKey=api_key)
    return _youtube_client


def extract_video_id(url: str) -> Optional[str]:
    """
    Extract YouTube video ID from various URL formats.
    Supports:
    - https://youtube.com/watch?v=dQw4w9WgXcQ
    - https://youtu.be/dQw4w9WgXcQ
    - https://www.youtube.com/embed/dQw4w9WgXcQ
    """
    patterns = [
        r"(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/)([^&\n?#]+)",
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    
    return None


def validate_youtube_video(
    url: str,
    patrol_name: str = "",
) -> dict:
    """
    Validate a YouTube video against Scout submission requirements.
    
    Args:
        url: YouTube video URL
        patrol_name: Patrol name for tag matching
    
    Returns:
        {
            "valid": bool,
            "video_id": str,
            "embed_url": str,
            "title": str,
            "duration_seconds": int,
            "privacy_status": str,
            "errors": list[str],
            "warnings": list[str],
            "metadata": {
                "channel_title": str,
                "publish_date": str,
                "description": str,
                "tags": list[str],
            }
        }
    """
    try:
        youtube = _get_youtube_client()
    except ValueError as e:
        return {
            "valid": False,
            "video_id": None,
            "embed_url": None,
            "errors": [str(e)],
            "warnings": [],
            "metadata": {},
        }
    
    video_id = extract_video_id(url)
    if not video_id:
        return {
            "valid": False,
            "video_id": None,
            "embed_url": None,
            "errors": ["No se pudo extraer el ID del video de YouTube"],
            "warnings": [],
            "metadata": {},
        }
    
    errors = []
    warnings = []
    
    try:
        # Fetch video metadata
        request = youtube.videos().list(
            part="snippet,contentDetails,status",
            id=video_id,
        )
        response = request.execute()
        
        if not response.get("items"):
            return {
                "valid": False,
                "video_id": video_id,
                "embed_url": f"https://www.youtube.com/embed/{video_id}",
                "errors": ["Video no encontrado o no accessible"],
                "warnings": [],
                "metadata": {},
            }
        
        video = response["items"][0]
        snippet = video.get("snippet", {})
        content_details = video.get("contentDetails", {})
        status = video.get("status", {})
        
        title = snippet.get("title", "")
        description = snippet.get("description", "")
        duration_str = content_details.get("duration", "PT0S")  # ISO 8601 format
        privacy_status = status.get("privacyStatus", "unknown")
        channel_title = snippet.get("channelTitle", "")
        publish_date = snippet.get("publishedAt", "")
        tags = snippet.get("tags", [])
        
        # Parse duration (ISO 8601 to seconds)
        duration_seconds = _parse_iso_duration(duration_str)
        
        # ===== VALIDATION CHECKS =====
        
        # 1. Privacy check
        if privacy_status == "private":
            errors.append("El video es privado. Debe ser 'No listado' o 'Público'.")
        elif privacy_status == "unknown":
            warnings.append("Estado de privacidad desconocido. Verifica que sea accesible.")
        
        # 2. Duration check (60-180 seconds)
        if duration_seconds < 60:
            errors.append(
                f"El video es demasiado corto ({duration_seconds}s). Mínimo: 60 segundos."
            )
        elif duration_seconds > 180:
            errors.append(
                f"El video es demasiado largo ({duration_seconds}s). Máximo: 180 segundos."
            )
        
        # 3. Tag/Title check (#LigiloScout or patrol name)
        has_ligilo_tag = "#LigiloScout" in title or "#LigiloScout" in description
        has_patrol_name = (
            patrol_name.lower() in title.lower()
            or patrol_name.lower() in description.lower()
        )
        
        if not (has_ligilo_tag or has_patrol_name):
            errors.append(
                f"El título/descripción debe contener '#LigiloScout' o el nombre de la patrulla '{patrol_name}'."
            )
        
        # Create embed URL
        embed_url = f"https://www.youtube.com/embed/{video_id}"
        
        result = {
            "valid": len(errors) == 0,
            "video_id": video_id,
            "embed_url": embed_url,
            "title": title,
            "duration_seconds": duration_seconds,
            "privacy_status": privacy_status,
            "errors": errors,
            "warnings": warnings,
            "metadata": {
                "channel_title": channel_title,
                "publish_date": publish_date,
                "description": description,
                "tags": tags,
            },
        }
        
        return result
        
    except HttpError as e:
        return {
            "valid": False,
            "video_id": video_id,
            "embed_url": f"https://www.youtube.com/embed/{video_id}",
            "errors": [f"Error de YouTube API: {str(e)[:100]}"],
            "warnings": [],
            "metadata": {},
        }
    except Exception as e:
        return {
            "valid": False,
            "video_id": video_id,
            "embed_url": f"https://www.youtube.com/embed/{video_id}",
            "errors": [f"Error procesando video: {str(e)[:100]}"],
            "warnings": [],
            "metadata": {},
        }


def _parse_iso_duration(duration_str: str) -> int:
    """
    Convert ISO 8601 duration format to seconds.
    Example: PT1M30S = 90 seconds, PT2H10M = 7800 seconds
    """
    if not duration_str or not duration_str.startswith("PT"):
        return 0
    
    duration_str = duration_str[2:]  # Remove 'PT'
    total_seconds = 0
    
    time_parts = re.findall(r"(\d+)([SMHD])", duration_str)
    for value, unit in time_parts:
        value = int(value)
        if unit == "H":
            total_seconds += value * 3600
        elif unit == "M":
            total_seconds += value * 60
        elif unit == "S":
            total_seconds += value
    
    return total_seconds
