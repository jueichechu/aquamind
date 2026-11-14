# Reviewed voice input

The bill-and-meter workspace at `/meter` accepts a short WAV voice clip as an
alternative to typing a question. This first version uses file selection; live
microphone recording, MP3/M4A/WebM input and spoken answers are not implemented.
Text input remains available without uploading audio.

## Website workflow

Import and review the [meter readings](meter-import.md), then add the bill as
described in the [combined evidence guide](evidence-agent.md). Under **Use a voice
clip instead of typing**, choose a supported file and explicitly allow external
AI transcription. Choosing a file alone does not upload it or call a provider.

The clip must be an uncompressed 16-bit PCM WAV, mono or stereo, at 8–48 kHz,
0.5–30 seconds long and at most 3 MiB. Extension and size are checked locally;
the server validates the RIFF structure, PCM format, sample alignment, actual
duration and nonempty/nonzero sample data before reserving a paid stage. Metadata
chunks are removed before the provider request. Original filenames are not sent.
Unsupported files need conversion outside this application, or typed input.

Transcription fills the existing editable question field and focuses it. Check
and correct the transcript, confirm its review, then separately allow AI to read
the bill, selected readings and question. Only **Ask with bill and meter** starts
the reasoning turn. Spoken instructions cannot approve actions. Transcript review
is a local acknowledgement, not an independent verification or approval record.

Evidence inputs stay locked while transcription runs. Selecting a new clip resets
audio consent; every transcription attempt clears sharing consent and the previous
answer. Failure preserves the existing question, focuses a generic error and
requires a deliberate new attempt. There are no automatic paid retries. Successful
transcription drops the selected file from the form; editing the question resets
transcript review and answer-sharing consent. Clearing/replacing meter evidence or
ending the session removes the whole combined form.

## Configuration and API

The existing `OPENAI_API_KEY` is reused. `OPENAI_TRANSCRIPTION_MODEL` is optional
and defaults to `gpt-transcribe`; it is selected only by the host. Existing
`OPENAI_MODEL` still selects the separate reasoning model. The existing agent and
meter-import flags must be enabled. No additional storage or compute service is
introduced. Public usage caps, free-service availability and provider account/model
access still apply; transcription and answering each reserve their own paid stage.

`POST /v1/audio/transcribe` requires a live bearer session and JSON containing
only `media_type: "audio/wav"`, `data_base64` and `share_with_ai: true`. Consent must
be a literal JSON boolean. Raw audio is capped at 3 MiB; the full encoded JSON body
is capped at 4 MiB + 1 KiB, including escaping. Duplicate keys, non-finite numbers,
unknown fields, client-selected models and malformed audio are rejected.

A successful response contains only `text`, integer `duration_ms`,
`source: "audio_transcription"`, `needs_review: true` and `request_id`. Text is
nonempty, at most 2,000 characters and 8 KiB. It is untrusted model output and is
rendered as escaped text, not markup or instructions. It is not automatically
sent to another model or tools. The subsequent explicit question uses the existing
evidence endpoint and its topic, period, session and scoped-tool checks.

Both same-origin relays allow only POST and enforce actual-byte body limits and
the existing paid-request deadline. Authentication/size/media/schema errors use
401/413/415/422; disabled voice support uses 404. Existing busy/pending-goal/budget
controls use 409/429; provider or configuration failures use generic 502/503 errors.
Session liveness is checked before work and before releasing text. Pending goal
checkpoints are preserved and must be resolved through the existing trusted flow.

## Privacy and limitations

Only the canonical audio file is sent to the transcription service: no bill,
meter data, session credential, tool definitions or prior transcript is included.
Audio/text stays out of application logs and durable storage. Browser credentials,
files and transcript state remain in memory; reload does not restore them.
The separate bill/meter question shares only the reviewed text and disclosed
evidence, without sending audio again. Revocation cannot undo a request already
sent to a provider.

The [OpenAI transcription API](https://developers.openai.com/api/docs/guides/speech-to-text)
does not expose the Responses API's `store` parameter. This implementation sends
no `store` field or Files API upload and disables SDK retries. Consult the
[provider data controls](https://developers.openai.com/api/docs/guides/your-data)
for current retention rules. Review remains necessary: accents, noise, silence,
numbers and units can be mistranscribed or hallucinated. A valid WAV container does
not prove speech or transcription accuracy. No accuracy benchmark is claimed here.

## Checks

```sh
PYTHONPATH=ml ml/.venv/bin/python -m unittest discover -s ml/tests -p test_voice.py -v
pnpm --filter web test src/lib/voice.test.ts src/app/meter/meter-workspace.test.tsx
```

Tests use the real SDK with a simulated provider to exercise strict consent,
format/duration/byte limits, metadata removal, bounded output, failures/timeouts,
session expiry/revocation, shared budgets and retained pending approvals. UI checks
cover unchecked sharing, loading locks, review/edit reset, focus, malformed replies,
failure without retries and explicit sending. Cloud CI runs without PyTorch; the
combined-service check sends maximum-body invalid-consent and overlong-audio
requests offline within the existing 512-MB runtime limit. These are regression
and integration checks, not representative speech-recognition measurements.
