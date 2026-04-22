"""
Certificate Generator Service
==============================
Sprint 3: Generates Scout Excellence Certificates (PDF) with heraldic design.

Features:
- SEL/Scout heraldic design
- QR code for validation (from SteloCertification JWT)
- Patrol details and achievement level
- Digital signature with timestamp
"""
import io
from pathlib import Path
from datetime import datetime
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor, gold, navy
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph
from PIL import Image, ImageDraw, ImageFont
import qrcode
import base64


def generate_excellence_certificate(
    patrol_name: str,
    patrol_delegation: str,
    tier: str,
    certification_code: str,
    qr_png_b64: str,
    scout_leader: str = "Scout Leader",
) -> bytes:
    """
    Generate an Excellence Certificate PDF in landscape format.
    
    Args:
        patrol_name: Name of the scout patrol
        patrol_delegation: Delegation/region name
        tier: Certification tier (bronze/silver/gold)
        certification_code: Unique cert code for validation
        qr_png_b64: Base64-encoded QR PNG image
        scout_leader: Name of scout leader (optional)
    
    Returns:
        PDF bytes ready to download or embed
    """
    # Create PDF in-memory
    pdf_buffer = io.BytesIO()
    
    # Use landscape orientation (11x8.5 inches)
    width, height = landscape(letter)
    
    c = canvas.Canvas(pdf_buffer, pagesize=landscape(letter))
    
    # ===== BACKGROUND & DESIGN =====
    
    # Decorative border
    border_color = _get_tier_color(tier)
    c.setStrokeColor(border_color)
    c.setLineWidth(3)
    c.rect(0.4*inch, 0.3*inch, width - 0.8*inch, height - 0.6*inch)
    
    # Inner decorative line
    c.setLineWidth(1)
    c.rect(0.55*inch, 0.45*inch, width - 1.1*inch, height - 0.9*inch)
    
    # ===== HEADER SECTION =====
    
    # Title: "Certificado de Excelencia Lingüística"
    c.setFont("Helvetica-BoldOblique", 28)
    c.setFillColor(navy)
    title_y = height - 0.8*inch
    c.drawCentredString(width/2, title_y, "Certificado de Excelencia")
    c.drawCentredString(width/2, title_y - 0.4*inch, "Lingüística SEL")
    
    # Tier emoji and name
    tier_info = {
        "bronze": ("🥉", "Bronce", HexColor("#CD7F32")),
        "silver": ("🥈", "Plata", HexColor("#C0C0C0")),
        "gold": ("🥇", "Oro", HexColor("#FFD700")),
    }
    tier_emoji, tier_name, tier_color = tier_info.get(tier, ("⭐", "Excelencia", gold))
    
    c.setFont("Helvetica-Bold", 18)
    c.setFillColor(tier_color)
    c.drawString(0.7*inch, title_y - 1.0*inch, f"{tier_emoji} Nivel: {tier_name}")
    
    # ===== MAIN CONTENT SECTION =====
    
    content_y = title_y - 1.8*inch
    
    # "Se certifica que:" text
    c.setFont("Helvetica-Oblique", 12)
    c.setFillColor(navy)
    c.drawString(1.0*inch, content_y, "Se certifica que:")
    
    # Patrol name (highlighted)
    c.setFont("Helvetica-Bold", 20)
    c.setFillColor(navy)
    patrol_name_y = content_y - 0.35*inch
    c.drawCentredString(width/2, patrol_name_y, patrol_name)
    
    # Decorative line under patrol name
    c.setStrokeColor(tier_color)
    c.setLineWidth(2)
    c.line(width/2 - 2*inch, patrol_name_y - 0.15*inch, width/2 + 2*inch, patrol_name_y - 0.15*inch)
    
    # Achievement text
    c.setFont("Helvetica", 12)
    c.setFillColor(navy)
    achievement_y = patrol_name_y - 0.6*inch
    c.drawCentredString(
        width/2,
        achievement_y,
        "ha alcanzado el nivel de"
    )
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(width/2, achievement_y - 0.3*inch, f"Protagonista Global en Esperanto")
    
    c.setFont("Helvetica", 11)
    c.setFillColor(HexColor("#333333"))
    achievement_y -= 0.7*inch
    c.drawCentredString(
        width/2,
        achievement_y,
        f"Delegación: {patrol_delegation}"
    )
    
    # ===== QR & VALIDATION SECTION =====
    
    qr_x = width - 2.2*inch
    qr_y = 0.7*inch
    qr_size = 1.8*inch
    
    # Convert base64 QR to image and embed
    if qr_png_b64:
        try:
            qr_data = base64.b64decode(qr_png_b64)
            qr_img = Image.open(io.BytesIO(qr_data))
            
            # Save temp QR image for PDF embedding
            qr_temp = io.BytesIO()
            qr_img.save(qr_temp, format='PNG')
            qr_temp.seek(0)
            
            c.drawImage(
                qr_temp,
                qr_x,
                qr_y,
                width=qr_size,
                height=qr_size,
                preserveAspectRatio=True,
            )
        except Exception as e:
            print(f"Error embedding QR: {e}")
            # Fallback: draw a placeholder
            c.setFillColor(HexColor("#CCCCCC"))
            c.rect(qr_x, qr_y, qr_size, qr_size, fill=True, stroke=False)
    
    # Validation code below QR
    c.setFont("Helvetica", 9)
    c.setFillColor(HexColor("#666666"))
    c.drawCentredString(qr_x + qr_size/2, qr_y - 0.2*inch, "Validar código:")
    c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(qr_x + qr_size/2, qr_y - 0.35*inch, certification_code)
    
    # ===== FOOTER SECTION =====
    
    # Signature line
    footer_y = 0.4*inch
    c.setLineWidth(1)
    c.setStrokeColor(navy)
    c.line(0.7*inch, footer_y + 0.1*inch, 2.5*inch, footer_y + 0.1*inch)
    c.line(width - 2.5*inch, footer_y + 0.1*inch, width - 0.7*inch, footer_y + 0.1*inch)
    
    # Signature text
    c.setFont("Helvetica", 10)
    c.setFillColor(navy)
    c.drawString(0.9*inch, footer_y - 0.1*inch, "Scout Leader")
    c.drawRightString(width - 0.9*inch, footer_y - 0.1*inch, "SEL Oficial")
    
    # Date and seal
    c.setFont("Helvetica-Oblique", 8)
    c.setFillColor(HexColor("#999999"))
    now = datetime.now()
    date_str = now.strftime("%d de %B de %Y")
    c.drawCentredString(width/2, 0.15*inch, f"Expedido: {date_str}")
    c.drawCentredString(width/2, 0.02*inch, "Ligilo - Scouts del Esperanto")
    
    # Finish PDF
    c.save()
    
    # Return PDF bytes
    pdf_buffer.seek(0)
    return pdf_buffer.getvalue()


def _get_tier_color(tier: str) -> HexColor:
    """Get color for tier."""
    colors = {
        "bronze": HexColor("#CD7F32"),
        "silver": HexColor("#C0C0C0"),
        "gold": HexColor("#FFD700"),
    }
    return colors.get(tier, navy)


def generate_wall_of_fame_thumbnail(
    patrol_name: str,
    tier: str,
    video_embed_url: str,
) -> dict:
    """
    Generate thumbnail data for Wall of Fame display.
    
    Returns:
        {
            "patrol_name": str,
            "tier": str,
            "video_embed_url": str,
            "tier_emoji": str,
            "tier_color": str,
        }
    """
    tier_info = {
        "bronze": ("🥉", "#CD7F32"),
        "silver": ("🥈", "#C0C0C0"),
        "gold": ("🥇", "#FFD700"),
    }
    tier_emoji, tier_color = tier_info.get(tier, ("⭐", "#FFD700"))
    
    return {
        "patrol_name": patrol_name,
        "tier": tier,
        "video_embed_url": video_embed_url,
        "tier_emoji": tier_emoji,
        "tier_color": tier_color,
    }


def generate_mcer_certificate(
    patrol_name: str,
    sister_patrol_name: str,
    delegation_name: str,
    mcer_level: str,
    points: int,
    match_start_date: str,
    certification_code: str,
    qr_png_b64: str,
    leader_name: str = "Scout Leader",
    with_watermark: bool = False,
) -> bytes:
    """
    Generate MCER Linguistic Excellence Certificate (Atestilo) PDF.
    
    Args:
        patrol_name: Primary patrol name
        sister_patrol_name: Sister patrol name (Ligilo/Link concept)
        delegation_name: Delegation name
        mcer_level: A1, A2, B1, or B2
        points: Current SEL points
        match_start_date: Date when patrols were matched
        certification_code: Unique certificate code
        qr_png_b64: Base64-encoded QR code PNG
        leader_name: Scout leader name
        with_watermark: If True, adds "PREVISUALIZACIÓN" watermark
    
    Returns:
        PDF bytes
    """
    pdf_buffer = io.BytesIO()
    width, height = landscape(letter)
    c = canvas.Canvas(pdf_buffer, pagesize=landscape(letter))
    
    # Background and border
    border_color = _get_mcer_level_color(mcer_level)
    c.setStrokeColor(border_color)
    c.setLineWidth(4)
    c.rect(0.3*inch, 0.2*inch, width - 0.6*inch, height - 0.4*inch)
    
    c.setLineWidth(1.5)
    c.rect(0.45*inch, 0.35*inch, width - 0.9*inch, height - 0.7*inch)
    
    # WATERMARK if preview mode
    if with_watermark:
        c.saveState()
        c.setFont("Helvetica-Bold", 72)
        c.setFillColor(HexColor("#FF0000"))
        c.setFillAlpha(0.15)
        c.translate(width/2, height/2)
        c.rotate(45)
        c.drawCentredString(0, 0, "PREVISUALIZACIÓN")
        c.restoreState()
    
    # Header: Certificate Title
    c.setFont("Helvetica-Bold", 32)
    c.setFillColor(navy)
    title_y = height - 0.9*inch
    c.drawCentredString(width/2, title_y, "Atestilo de Ligilo")
    
    c.setFont("Helvetica-Oblique", 16)
    c.drawCentredString(width/2, title_y - 0.35*inch, "Certificado de Excelencia Lingüística SEL")
    
    # MCER Level Badge
    level_info = {
        "A1": ("🌱", "A1 Malkovranto", HexColor("#90EE90")),
        "A2": ("🌿", "A2 Vojtrovanto", HexColor("#32CD32")),
        "B1": ("🌲", "B1 Esploristo", HexColor("#228B22")),
        "B2": ("🏔️", "B2 Gvidanto", HexColor("#006400")),
    }
    level_emoji, level_label, level_color = level_info.get(mcer_level, ("⭐", mcer_level, gold))
    
    c.setFont("Helvetica-Bold", 22)
    c.setFillColor(level_color)
    level_y = title_y - 1.1*inch
    c.drawString(0.8*inch, level_y, f"{level_emoji} {level_label}")
    
    # Main content
    content_y = level_y - 0.6*inch
    c.setFont("Helvetica", 12)
    c.setFillColor(navy)
    c.drawString(1.2*inch, content_y, "Se certifica que las patrullas hermanas:")
    
    # Patrol names (intertwined - Ligilo concept)
    c.setFont("Helvetica-Bold", 18)
    names_y = content_y - 0.4*inch
    c.drawCentredString(width/2, names_y, f"{patrol_name} ⛓️ {sister_patrol_name}")
    
    c.setFont("Helvetica-Oblique", 11)
    c.drawCentredString(width/2, names_y - 0.3*inch, f"Delegación: {delegation_name}")
    
    # Achievement text
    achievement_y = names_y - 0.8*inch
    c.setFont("Helvetica", 12)
    c.drawString(1.2*inch, achievement_y, f"Han completado el hermanamiento internacional con excelencia,")
    c.drawString(1.2*inch, achievement_y - 0.25*inch, f"alcanzando el nivel {mcer_level} del Marco Común Europeo de Referencia")
    c.drawString(1.2*inch, achievement_y - 0.5*inch, f"para las Lenguas (MCER) en Esperanto.")
    
    # Points and dates
    details_y = achievement_y - 1.0*inch
    c.setFont("Helvetica-Bold", 11)
    c.drawString(1.2*inch, details_y, f"Puntos SEL acumulados: {points}")
    c.drawString(1.2*inch, details_y - 0.2*inch, f"Fecha de hermanamiento: {match_start_date}")
    c.drawString(1.2*inch, details_y - 0.4*inch, f"Código de certificación: {certification_code}")
    
    # Signatures section
    sig_y = 1.2*inch
    c.setFont("Helvetica", 10)
    
    # Leader signature
    c.drawString(1.5*inch, sig_y, "_" * 30)
    c.drawString(1.5*inch, sig_y - 0.2*inch, f"{leader_name}")
    c.drawString(1.5*inch, sig_y - 0.35*inch, "Líder de Unidad SEL")
    
    # AI Skolto-Instruisto signature
    c.drawString(5.5*inch, sig_y, "_" * 30)
    c.drawString(5.5*inch, sig_y - 0.2*inch, "Skolto-Instruisto (IA)")
    c.drawString(5.5*inch, sig_y - 0.35*inch, "Validador Automático")
    
    # QR Code (Wall of Fame link)
    if qr_png_b64:
        try:
            qr_img = Image.open(io.BytesIO(base64.b64decode(qr_png_b64)))
            qr_path = Path("temp_qr.png")
            qr_img.save(qr_path)
            c.drawImage(str(qr_path), width - 1.8*inch, sig_y - 0.5*inch, 1.3*inch, 1.3*inch)
            qr_path.unlink()
        except Exception:
            pass  # Skip QR if decode fails
    
    c.setFont("Helvetica-Oblique", 8)
    c.drawString(width - 1.8*inch, sig_y - 0.7*inch, "Escanea para ver")
    c.drawString(width - 1.8*inch, sig_y - 0.85*inch, "Muro de la Fama")
    
    c.showPage()
    c.save()
    
    pdf_buffer.seek(0)
    return pdf_buffer.read()


def _get_mcer_level_color(level: str) -> HexColor:
    """Get color for MCER level."""
    colors = {
        "A1": HexColor("#90EE90"),
        "A2": HexColor("#32CD32"),
        "B1": HexColor("#228B22"),
        "B2": HexColor("#006400"),
    }
    return colors.get(level, navy)
