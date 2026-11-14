"""Bounded, consented audio-to-text; never an agent turn or an approval."""

import asyncio
import base64
import binascii
import os
import re
import struct
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_AUDIO_BYTES = 3 * 1024 * 1024
MAX_AUDIO_BASE64 = 4 * ((MAX_AUDIO_BYTES + 2) // 3)
AUDIO_BODY_LIMIT = MAX_AUDIO_BASE64 + 1024


class VoiceRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, hide_input_in_errors=True)
    media_type: Literal['audio/wav']
    data_base64: str = Field(min_length=4, max_length=MAX_AUDIO_BASE64)
    share_with_ai: bool = Field(json_schema_extra={'const': True})

    @field_validator('share_with_ai', mode='before')
    @classmethod
    def explicit_consent(cls, value):
        if value is not True:
            raise ValueError('Explicit audio sharing is required')
        return value

    def checked_audio(self):
        try:
            raw = base64.b64decode(self.data_base64, validate=True)
            if not 44 <= len(raw) <= MAX_AUDIO_BYTES or raw[:4] != b'RIFF' or raw[8:12] != b'WAVE':
                raise ValueError()
            if struct.unpack_from('<I', raw, 4)[0] != len(raw) - 8:
                raise ValueError()
            offset, chunks, fmt, pcm = 12, 0, None, None
            while offset < len(raw):
                chunks += 1
                if chunks > 16 or offset + 8 > len(raw):
                    raise ValueError()
                kind, length = struct.unpack_from('<4sI', raw, offset)
                start = offset + 8
                end = start + length
                offset = end + (length % 2)
                if offset > len(raw):
                    raise ValueError()
                if kind == b'fmt ':
                    if fmt is not None or length not in (16, 18) or (length == 18 and raw[end-2:end] != b'\0\0'):
                        raise ValueError()
                    fmt = raw[start:start+16]
                elif kind == b'data':
                    if pcm is not None or fmt is None:
                        raise ValueError()
                    pcm = raw[start:end]
            if fmt is None or pcm is None:
                raise ValueError()
            encoding, channels, rate, byte_rate, align, bits = struct.unpack('<HHIIHH', fmt)
            if encoding != 1 or bits != 16 or channels not in (1, 2) or not 8000 <= rate <= 48000:
                raise ValueError()
            if align != channels * 2 or byte_rate != rate * align or len(pcm) % align:
                raise ValueError()
            frames = len(pcm) // align
            if not rate // 2 <= frames <= rate * 30 or not any(pcm):
                raise ValueError()
            # Send PCM and format only, without ancillary metadata or the original filename.
            canonical = (b'RIFF' + struct.pack('<I', 36 + len(pcm)) + b'WAVEfmt ' +
                         struct.pack('<I', 16) + fmt + b'data' + struct.pack('<I', len(pcm)) + pcm)
            return canonical, frames * 1000 // rate
        except (ValueError, binascii.Error, struct.error):
            raise HTTPException(422, 'Use a non-silent 16-bit PCM WAV, 0.5–30 seconds, up to 3 MiB, mono/stereo at 8–48 kHz') from None


class VoiceResponse(BaseModel):
    text: str
    duration_ms: int
    source: Literal['audio_transcription'] = 'audio_transcription'
    needs_review: Literal[True] = True
    request_id: str


async def transcribe_clip(client, config, audio, duration_ms):
    model = os.environ.get('OPENAI_TRANSCRIPTION_MODEL', 'gpt-transcribe')
    if not re.fullmatch(r'[a-z][a-z0-9.-]{0,79}', model):
        raise HTTPException(503, 'Voice transcription unavailable')
    async with asyncio.timeout(config.request_timeout_seconds):
        result = await client.with_options(max_retries=0, timeout=config.request_timeout_seconds).audio.transcriptions.create(
            model=model, file=('voice-clip.wav', audio, 'audio/wav'), response_format='json')
    text = result.text
    if not isinstance(text, str) or not text.strip() or len(text) > 2000 or len(text.encode()) > 8192:
        raise HTTPException(502, 'Transcript could not be read; type your question instead')
    return {'text': text.strip(), 'duration_ms': duration_ms}
