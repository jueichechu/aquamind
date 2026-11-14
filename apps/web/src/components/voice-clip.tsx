"use client";

import { useEffect, useRef, useState } from 'react';
import { checkVoiceFile } from '../lib/voice';

export function VoiceClip({transcribe, locked, onBusyChange, onTranscript}: {
  transcribe:(file:File,consent:boolean)=>Promise<string>; locked:boolean;
  onBusyChange:(busy:boolean)=>void; onTranscript:(text:string)=>void;
}) {
  const [file,setFile]=useState<File|null>(null);
  const [share,setShare]=useState(false);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [notice,setNotice]=useState('');
  const input=useRef<HTMLInputElement>(null), alert=useRef<HTMLParagraphElement>(null);
  const working=useRef(false), mounted=useRef(false);
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;};},[]);
  useEffect(()=>{if(error)alert.current?.focus();},[error]);
  function clear(){setFile(null);setShare(false);if(input.current)input.current.value='';}
  async function convert(){
    if(working.current||locked||!file||!share)return;
    working.current=true;setBusy(true);setError('');setNotice('');onBusyChange(true);
    try {
      const text=await transcribe(file,true);
      if(!mounted.current)return;
      onTranscript(text);clear();setNotice('Transcript added to your question. Check and correct it before sending.');
    }catch(cause){if(mounted.current)setError(cause instanceof Error?cause.message:'The clip could not be transcribed. Type your question instead.');}
    finally{working.current=false;if(mounted.current){setBusy(false);setShare(false);}onBusyChange(false);}
  }
  return <details className="text-sm leading-6">
    <summary className="ui-link cursor-pointer">Use a voice clip instead of typing</summary>
    <fieldset disabled={locked||busy} className="mt-4 min-w-0 space-y-3" aria-busy={busy}>
      <legend className="sr-only">Optional voice transcription</legend>
      <div><label htmlFor="evidence-voice-file" className="block">Voice clip (WAV)</label>
        <input ref={input} id="evidence-voice-file" type="file" accept=".wav,audio/wav,audio/x-wav" className="ui-field mt-2" aria-describedby="evidence-voice-format"
          onChange={event=>{if(working.current)return;setShare(false);setError('');setNotice('');setFile(null);
            const chosen=event.target.files?.[0];if(!chosen)return;
            try{checkVoiceFile(chosen);setFile(chosen);}catch(cause){event.target.value='';setError(cause instanceof Error?cause.message:'Choose a WAV clip.');}}}/></div>
      <p id="evidence-voice-format" className="text-xs leading-5 text-muted">16-bit PCM WAV, 0.5–30 seconds, up to 3 MiB; mono/stereo at 8–48 kHz. You can always type instead.</p>
      {file && <>
        <p id="evidence-voice-sharing" className="text-ink-secondary">An external AI service transcribes this clip. Leave out personal details. Audio is not saved by this application. You review the transcript before asking AI about your bill. <a className="ui-link underline underline-offset-4" href="https://developers.openai.com/api/docs/guides/your-data" target="_blank" rel="noopener noreferrer">Data policy</a></p>
        <label className="flex min-h-11 items-start gap-3"><input id="evidence-voice-consent" type="checkbox" checked={share} aria-describedby="evidence-voice-sharing"
          className="mt-1 size-4 shrink-0 accent-accent" onChange={event=>setShare(event.target.checked)}/>Allow AI to transcribe this voice clip.</label>
        <div className="flex flex-wrap gap-3"><button type="button" className="ui-button ui-button-secondary" disabled={!share||busy||locked} onClick={()=>void convert()}>{busy?'Transcribing clip…':'Transcribe clip'}</button>
          <button type="button" className="ui-button ui-button-secondary" onClick={()=>{clear();setNotice('');setError('');input.current?.focus();}}>Remove clip</button></div>
      </>}
    </fieldset>
    <p role="status" aria-atomic="true" className="mt-2 text-ink-secondary">{busy?'Transcribing your clip. There is no automatic retry.':notice}</p>
    {error && <p ref={alert} role="alert" tabIndex={-1} className="mt-3 rounded-lg border border-warning bg-warning-soft p-3 text-warning focus-visible:outline-2 focus-visible:outline-warning">{error}</p>}
  </details>;
}
