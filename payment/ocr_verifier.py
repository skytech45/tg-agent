"""
payment/ocr_verifier.py — UPI payment screenshot verification using OCR.

Flow:
1. User sends a payment screenshot.
2. Bot downloads the image from Telegram.
3. OCR extracts text from the image.
4. Regex patterns validate UPI transaction ID, amount, and status.
5. Returns a PaymentResult with verified=True/False and details.
"""

import re
from dataclasses import dataclass, field
from io import BytesIO
from typing import Optional, Tuple

import httpx
from PIL import Image, ImageEnhance, ImageFilter
from loguru import logger

try:
    import pytesseract
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False
    logger.warning("pytesseract not installed — OCR verification disabled")


# ── Regex patterns for UPI payment details ──
PATTERNS = {
    "txn_id": re.compile(
        r"(?:UPI\s*Ref\.?\s*(?:No\.?|ID)?|Transaction\s*ID|Txn\s*ID|UTR)[:\s]*([A-Z0-9]{10,25})",
        re.IGNORECASE,
    ),
    "amount": re.compile(
        r"(?:₹|Rs\.?|INR)\s*([\d,]+(?:\.\d{1,2})?)",
        re.IGNORECASE,
    ),
    "status_success": re.compile(
        r"\b(payment\s+successful|paid|success|completed|debited)\b",
        re.IGNORECASE,
    ),
    "status_failure": re.compile(
        r"\b(failed|declined|rejected|cancelled|pending)\b",
        re.IGNORECASE,
    ),
    "upi_id": re.compile(
        r"[a-zA-Z0-9.\-_]{2,256}@[a-zA-Z]{2,64}",
    ),
}


@dataclass
class PaymentResult:
    verified: bool
    txn_id: Optional[str] = None
    amount: Optional[float] = None
    upi_id: Optional[str] = None
    status_text: str = ""
    raw_text: str = ""
    reason: str = ""
    confidence: float = 0.0


def preprocess_image(img: Image.Image) -> Image.Image:
    """Enhance image quality for better OCR accuracy."""
    img = img.convert("L")  # Grayscale
    img = img.filter(ImageFilter.SHARPEN)
    enhancer = ImageEnhance.Contrast(img)
    img = enhancer.enhance(2.0)
    # Scale up small images
    w, h = img.size
    if w < 800:
        img = img.resize((w * 2, h * 2), Image.LANCZOS)
    return img


def extract_text(img: Image.Image) -> str:
    """Run Tesseract OCR on a preprocessed image."""
    if not OCR_AVAILABLE:
        return ""
    processed = preprocess_image(img)
    config = "--oem 3 --psm 6 -l eng"
    return pytesseract.image_to_string(processed, config=config)


def parse_payment_text(text: str) -> PaymentResult:
    """Parse extracted OCR text and validate payment details."""
    result = PaymentResult(verified=False, raw_text=text)

    # Extract transaction ID
    txn_match = PATTERNS["txn_id"].search(text)
    if txn_match:
        result.txn_id = txn_match.group(1).strip()

    # Extract amount
    amt_match = PATTERNS["amount"].search(text)
    if amt_match:
        try:
            result.amount = float(amt_match.group(1).replace(",", ""))
        except ValueError:
            pass

    # Extract UPI ID
    upi_match = PATTERNS["upi_id"].search(text)
    if upi_match:
        result.upi_id = upi_match.group(0)

    # Check payment status
    if PATTERNS["status_failure"].search(text):
        result.verified = False
        result.status_text = "failed"
        result.reason = "Payment screenshot shows a failed/pending transaction."
        return result

    success = bool(PATTERNS["status_success"].search(text))
    has_txn = result.txn_id is not None
    has_amount = result.amount is not None

    score = sum([success, has_txn, has_amount])
    result.confidence = score / 3.0

    if success and has_txn:
        result.verified = True
        result.status_text = "success"
        result.reason = "Payment verified via OCR."
    elif score >= 2:
        result.verified = True
        result.status_text = "likely_success"
        result.reason = "Payment likely successful (partial match)."
        result.confidence = 0.7
    else:
        result.verified = False
        result.status_text = "unverified"
        result.reason = "Could not confirm payment — please send a clearer screenshot."

    return result


async def verify_payment_screenshot(
    file_url: str,
    expected_amount: Optional[float] = None,
) -> PaymentResult:
    """
    Download a Telegram file URL and run payment verification.

    Args:
        file_url: Direct download URL for the image file.
        expected_amount: Optional expected payment amount to validate against.

    Returns:
        PaymentResult with verification outcome.
    """
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(file_url)
            response.raise_for_status()
            img = Image.open(BytesIO(response.content))

        text = extract_text(img)
        logger.debug(f"OCR extracted text ({len(text)} chars)")

        if not text.strip():
            return PaymentResult(
                verified=False,
                reason="Could not extract text from image. Please send a clearer screenshot.",
            )

        result = parse_payment_text(text)

        # Validate amount if expected
        if expected_amount and result.amount:
            if abs(result.amount - expected_amount) > 1.0:
                result.verified = False
                result.reason = (
                    f"Amount mismatch: expected ₹{expected_amount}, "
                    f"found ₹{result.amount}."
                )

        return result

    except httpx.HTTPError as e:
        logger.error(f"Failed to download payment screenshot: {e}")
        return PaymentResult(verified=False, reason="Failed to download image.")
    except Exception as e:
        logger.error(f"Payment verification error: {e}")
        return PaymentResult(verified=False, reason=f"Verification error: {str(e)}")
