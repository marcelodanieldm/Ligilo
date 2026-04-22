"""
Video Auditor Service
=====================
Sprint 3: Validates scout videos for authenticity and Esperanto proficiency.

Uses Google Cloud Vertex AI (Gemini Pro Vision) to analyze videos:
1. Detects if multiple people are participating (teamwork)
2. Verifies content matches the challenge (patrol presentation + dreams)
3. Rates Esperanto naturality

Requires:
- GOOGLE_CLOUD_PROJECT environment variable
- GOOGLE_APPLICATION_CREDENTIALS pointing to service account JSON
"""
import os
import asyncio
from typing import Optional
from asgiref.sync import sync_to_async


def _init_vertex_ai():
    """Initialize Vertex AI SDK."""
    try:
        import vertexai
        project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
        if not project_id:
            raise ValueError("GOOGLE_CLOUD_PROJECT environment variable not set")
        
        vertexai.init(project=project_id, location="us-central1")
        return True
    except ImportError:
        raise ImportError("google-cloud-aiplatform not installed")
    except Exception as e:
        raise RuntimeError(f"Failed to initialize Vertex AI: {e}")


async def audit_video_esperanto(
    video_url: str,
    video_id: str,
    patrol_name: str = "",
) -> dict:
    """
    Audit a YouTube video for scout challenge compliance.
    
    Uses Gemini Pro Vision to analyze video content:
    1. Detect multiple participants (teamwork indicator)
    2. Verify patrol presentation + dreams content
    3. Rate Esperanto naturality (fluidity, pronunciation, confidence)
    
    Args:
        video_url: Full YouTube URL
        video_id: YouTube video ID
        patrol_name: Patrol name for content verification
    
    Returns:
        {
            "audit_valid": bool,
            "errors": list[str],
            "findings": {
                "participants_count": int,
                "has_teamwork": bool,
                "content_match": bool,
                "content_match_reason": str,
                "esperanto_rating": float (0-10),
                "esperanto_feedback": str,
                "overall_authenticity": float (0-10),
                "transcript_excerpt": str,
            }
        }
    """
    try:
        _init_vertex_ai()
    except Exception as e:
        return {
            "audit_valid": False,
            "errors": [f"AI initialization failed: {str(e)[:100]}"],
            "findings": {},
        }
    
    # For now, we'll implement a simplified analysis using Gemini's video understanding
    # In production, you would download the video audio/extract frames and send to Gemini
    
    audit_result = await _analyze_video_with_gemini(video_url, video_id, patrol_name)
    return audit_result


async def _analyze_video_with_gemini(
    video_url: str,
    video_id: str,
    patrol_name: str,
) -> dict:
    """
    Analyze video using Google Cloud Vertex AI Gemini Pro Vision.
    
    This is an async wrapper that delegates to sync Vertex AI calls.
    """
    return await sync_to_async(_sync_analyze_with_gemini)(video_url, video_id, patrol_name)


def _sync_analyze_with_gemini(
    video_url: str,
    video_id: str,
    patrol_name: str,
) -> dict:
    """
    Synchronous analysis using Vertex AI Gemini Pro Vision.
    
    Note: Gemini Pro Vision on Vertex AI can process videos via YouTube links,
    but requires proper video access and quota setup.
    """
    try:
        import vertexai
        from vertexai.generative_models import GenerativeModel, Part
        
        model = GenerativeModel("gemini-1.5-pro-vision")
        
        # Create the audit prompt
        audit_prompt = f"""
Analiza este video de un scout de la SEL (Scouts del Esperanto Ligilo).

Tarea final del scout: Presentar su patrulla y sus sueños para el Jamboree en Esperanto.

Video URL: {video_url}

Por favor evalúa lo siguiente:

1. **Participantes & Trabajo en Equipo**:
   - ¿Cuántas personas participan activamente en el video?
   - ¿Es trabajo colaborativo o solo una persona?

2. **Contenido & Cumplimiento de Reto**:
   - ¿Presenta el video la patrulla? (nombre, número de miembros, localización)
   - ¿Incluye sueños/metas para el Jamboree?
   - ¿Responde al tema de 'protagonistas globales'?
   - Califica 0-10 qué tan bien cumple el reto

3. **Proficiencia en Esperanto**:
   - ¿Es el Esperanto hablado natural y fluido?
   - ¿Hay vacilaciones o pausas excesivas?
   - ¿La pronunciación es correcta?
   - Califica 0-10 la naturalidad del Esperanto
   - Proporciona feedback específico

4. **Autenticidad General**:
   - ¿Parece ser un video genuino (no editado/fake)?
   - ¿La energía y entusiasmo sugieren compromiso real?
   - Califica 0-10 la autenticidad general

Responde en JSON:
{{
    "participants_count": <número>,
    "has_teamwork": <bool>,
    "content_match": <bool>,
    "content_match_reason": "<explicación breve>",
    "esperanto_rating": <0-10>,
    "esperanto_feedback": "<feedback específico>",
    "overall_authenticity": <0-10>,
    "transcript_excerpt": "<frase representativa en Esperanto>",
    "audit_valid": <bool>,
    "audit_notes": "<notas importantes>"
}}
"""
        
        # For direct YouTube link support, we use the URL as is
        # Gemini can fetch and analyze YouTube videos directly
        content = [
            Part.from_text(audit_prompt),
            Part.from_uri(
                mime_type="video/mp4",
                uri=f"https://www.youtube.com/watch?v={video_id}"
            )
        ]
        
        response = model.generate_content(content)
        
        # Parse response
        response_text = response.text if hasattr(response, 'text') else ""
        
        # Extract JSON from response
        import json
        import re
        
        json_match = re.search(r"\{.*\}", response_text, re.DOTALL)
        if json_match:
            audit_data = json.loads(json_match.group())
        else:
            # Fallback: create reasonable audit based on response text
            audit_data = {
                "participants_count": 1,
                "has_teamwork": False,
                "content_match": False,
                "content_match_reason": "No se pudo analizar el video",
                "esperanto_rating": 0,
                "esperanto_feedback": "Análisis de video requerido",
                "overall_authenticity": 0,
                "transcript_excerpt": "",
                "audit_valid": False,
                "audit_notes": response_text[:200],
            }
        
        # Determine if audit passes
        audit_valid = (
            audit_data.get("content_match", False) and
            audit_data.get("esperanto_rating", 0) >= 6 and
            audit_data.get("overall_authenticity", 0) >= 6
        )
        
        return {
            "audit_valid": audit_valid,
            "errors": [] if audit_valid else ["Video no cumple requisitos de auditoría"],
            "findings": {
                "participants_count": audit_data.get("participants_count", 1),
                "has_teamwork": audit_data.get("has_teamwork", False),
                "content_match": audit_data.get("content_match", False),
                "content_match_reason": audit_data.get("content_match_reason", ""),
                "esperanto_rating": audit_data.get("esperanto_rating", 0),
                "esperanto_feedback": audit_data.get("esperanto_feedback", ""),
                "overall_authenticity": audit_data.get("overall_authenticity", 0),
                "transcript_excerpt": audit_data.get("transcript_excerpt", ""),
            },
        }
        
    except ImportError:
        return {
            "audit_valid": False,
            "errors": ["Vertex AI SDK not installed"],
            "findings": {},
        }
    except Exception as e:
        return {
            "audit_valid": False,
            "errors": [f"Audit error: {str(e)[:200]}"],
            "findings": {},
        }
