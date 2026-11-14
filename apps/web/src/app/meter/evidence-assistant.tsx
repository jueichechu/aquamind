"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { BillFields } from "../../components/bill-fields";
import { BillReadingNote, BillSourceHint } from "../../components/bill-evidence";
import { ReportImport } from "../../components/report-import";
import { VoiceClip } from "../../components/voice-clip";
import { IMPORT_WARNINGS, type ImportedBill } from "../../lib/bill-import";
import type { BillDraft } from "../../lib/bills";
import { MeterClient, MeterError, type MeterOptions, type MeterSummary } from "../../lib/meter-import";

const empty: BillDraft = {period_start:'',period_end_exclusive:'',usage:'',usage_unit:'',water_charge:'',sewer_charge:'',currency:''};

export function EvidenceAssistant({client, selected, onBusyChange, onSelectionLost}: {
  client: MeterClient; selected: MeterSummary; onBusyChange:(busy:boolean)=>void;
  onSelectionLost:(expired:boolean)=>void;
}) {
  const [draft,setDraft]=useState<BillDraft>(empty);
  const [imported,setImported]=useState<ImportedBill|null>(null);
  const [timezone,setTimezone]=useState('');
  const [reading,setReading]=useState<MeterOptions['reading_type']>('unknown');
  const [billReviewed,setBillReviewed]=useState(false);
  const [household,setHousehold]=useState(false);
  const [share,setShare]=useState(false);
  const [question,setQuestion]=useState('');
  const [fromVoice,setFromVoice]=useState(false), [voiceReviewed,setVoiceReviewed]=useState(false);
  const [busy,setBusy]=useState(false);
  const [extracting,setExtracting]=useState(false);
  const [answer,setAnswer]=useState('');
  const [error,setError]=useState('');
  const working=useRef(false), mounted=useRef(false);
  const alert=useRef<HTMLParagraphElement>(null), answerHeading=useRef<HTMLHeadingElement>(null);
  const questionInput=useRef<HTMLTextAreaElement>(null), focusTranscript=useRef(false);
  useEffect(()=>{mounted.current=true; return()=>{mounted.current=false;};},[]);
  useEffect(()=>{if(error) alert.current?.focus();},[error]);
  useEffect(()=>{if(answer) answerHeading.current?.focus({preventScroll:true});},[answer]);
  useEffect(()=>{if(focusTranscript.current&&!extracting){focusTranscript.current=false;questionInput.current?.focus();}},[question,extracting]);
  const reportClient=useMemo(()=>({importBill:async(file:File,consent:boolean)=>{
    try {return await client.importBill(file,consent);}
    catch(cause){if(cause instanceof MeterError && cause.expired) onSelectionLost(true); throw cause;}
  },transcribeVoice:async(file:File,consent:boolean)=>{
    try{return await client.transcribeVoice(file,consent);}
    catch(cause){if(cause instanceof MeterError&&cause.expired)onSelectionLost(true);throw cause;}
  }}),[client,onSelectionLost]);
  function invalidate(){setBillReviewed(false);setHousehold(false);setShare(false);setVoiceReviewed(false);setAnswer('');setError('');}
  function changeBill(field:keyof BillDraft,value:string){if(working.current)return;setDraft(previous=>({...previous,[field]:value}));invalidate();}
  function reportBusy(value:boolean){working.current=value;setExtracting(value);onBusyChange(value);if(value){setShare(false);setAnswer('');setError('');}}
  async function ask(){
    if(working.current || !billReviewed || !household || !share || !question.trim() || (fromVoice&&!voiceReviewed)) return;
    working.current=true;setBusy(true);onBusyChange(true);setError('');setAnswer('');
    try{
      const reply=await client.askEvidence(draft,timezone,imported?'document_import':'manual_entry',reading,
        selected.context.evidence_id,question.trim(),{bill_reviewed:billReviewed,meter_reviewed:true,same_household:household,share_with_ai:share});
      if(!mounted.current)return;
      if(reply.status==='answer') setAnswer(reply.answer);
      else setError(reply.status==='refused'?'Ask a question focused on the household’s bill, meter readings or conservation.':
        'The bill-and-meter answer could not be completed. There is no automatic retry.');
    }catch(cause){
      if(!mounted.current)return;
      if(cause instanceof MeterError && (cause.expired || cause.selectionChanged)) onSelectionLost(cause.expired);
      else setError(cause instanceof Error?cause.message:'The answer could not be confirmed. There is no automatic retry.');
    }finally{working.current=false;if(mounted.current){setBusy(false);setShare(false);}onBusyChange(false);}
  }
  return <section aria-labelledby="evidence-heading" className="min-w-0 border-t border-rule pt-6 lg:col-span-2">
    <h2 id="evidence-heading" className="text-2xl font-semibold">Ask about this bill and meter</h2>
    <p className="mt-3 max-w-3xl text-sm leading-6 text-ink-secondary">Add a bill for the same household. The selected meter period must fit inside it. Partial meter coverage cannot explain the full bill total.</p>
    <details className="mt-4 max-w-xl text-sm leading-6">
      <summary className="ui-link cursor-pointer">Read a bill document instead of typing</summary>
      <ReportImport client={reportClient} locked={busy||extracting} onBusyChange={reportBusy} manualHref="#evidence-bill-start"
        onSelectionChange={()=>{setDraft(empty);setImported(null);setReading('unknown');invalidate();}}
        onImported={result=>{setDraft(result.draft);setImported(result);setReading(result.evidence?.reading_type??'unknown');invalidate();}} />
    </details>
    {imported && <div className="mt-4 text-sm leading-6 text-ink-secondary"><BillReadingNote evidence={imported.evidence}/>
      {!!imported.warnings.length && <ul className="mt-3 list-disc pl-5">{imported.warnings.map(warning=><li key={warning}>{IMPORT_WARNINGS[warning]}</li>)}</ul>}
      <p className="mt-3">Imported fields are editable candidates. Review them against the original; edits and review do not verify them.</p></div>}
    <form method="post" autoComplete="off" aria-busy={busy||extracting} className="mt-5"
      onSubmit={event=>{event.preventDefault();void ask();}}>
      <fieldset disabled={busy||extracting} className="grid min-w-0 items-start gap-8 lg:grid-cols-2">
        <legend className="sr-only">Bill fields, review and AI sharing</legend>
        <div className="min-w-0 space-y-5"><BillFields draft={draft} onChange={changeBill} idPrefix="evidence-bill"
          descriptionIds={(field,help)=>[help,imported?.evidence?`evidence-${field}-source`:undefined].filter(Boolean).join(' ')||undefined}
          sourceHint={(field,required)=>imported?.evidence?<BillSourceHint id={`evidence-${field}-source`} source={imported.evidence.fields[field]}
            changed={draft[field]!==imported.draft[field]} empty={!draft[field].trim()} required={!!required} reviewed={billReviewed}/>:null}/>
          <button type="button" className="ui-button ui-button-secondary" onClick={()=>{setDraft(empty);setImported(null);setReading('unknown');invalidate();}}>Clear evidence bill</button>
        </div>
        <div className="min-w-0 space-y-5">
          <div><label htmlFor="evidence-timezone" className="block text-sm">Bill timezone (required)</label>
            <input id="evidence-timezone" required maxLength={64} value={timezone} placeholder="America/Los_Angeles"
              className="ui-field mt-2" aria-describedby="evidence-timezone-help" onChange={event=>{setTimezone(event.target.value);invalidate();}}/>
            <p id="evidence-timezone-help" className="mt-2 text-xs leading-5 text-muted">Use the bill’s local calendar timezone. The meter export uses {selected.timezone}; do not assume they match.</p></div>
          <div><label htmlFor="evidence-reading" className="block text-sm">Bill reading type, reported by you</label>
            <select id="evidence-reading" value={reading} className="ui-field mt-2" onChange={event=>{setReading(event.target.value as MeterOptions['reading_type']);invalidate();}}>
              <option value="unknown">Not identified</option><option value="actual">Actual</option><option value="estimated">Estimated</option><option value="mixed">Mixed</option>
            </select></div>
          <label className="flex min-h-11 items-start gap-3 text-sm leading-6"><input id="evidence-reviewed" type="checkbox" required checked={billReviewed}
            className="mt-1 size-4 shrink-0 accent-accent" onChange={event=>{setBillReviewed(event.target.checked);setShare(false);setAnswer('');}}/>I checked the bill dates, units, usage and optional charges against my report.</label>
          <label className="flex min-h-11 items-start gap-3 text-sm leading-6"><input id="evidence-household" type="checkbox" required checked={household}
            className="mt-1 size-4 shrink-0 accent-accent" onChange={event=>{setHousehold(event.target.checked);setShare(false);setAnswer('');}}/>This bill and the selected meter readings are for the same household.</label>
          <VoiceClip transcribe={reportClient.transcribeVoice} locked={busy||extracting} onBusyChange={reportBusy}
            onTranscript={text=>{focusTranscript.current=true;setQuestion(text);setFromVoice(true);setVoiceReviewed(false);setShare(false);setAnswer('');setError('');}}/>
          <div><label htmlFor="evidence-question" className="block text-sm">Your household-water question</label>
            <textarea ref={questionInput} id="evidence-question" required rows={3} maxLength={2000} value={question} className="ui-field mt-2 resize-y"
              placeholder="What can these readings tell me about my bill, and what is still missing?"
              onChange={event=>{setQuestion(event.target.value);setVoiceReviewed(false);setShare(false);setAnswer('');setError('');}}/></div>
          {fromVoice && <label className="flex min-h-11 items-start gap-3 text-sm leading-6"><input id="evidence-voice-reviewed" type="checkbox" required checked={voiceReviewed}
            className="mt-1 size-4 shrink-0 accent-accent" onChange={event=>{setVoiceReviewed(event.target.checked);setShare(false);setAnswer('');}}/>I checked the transcript and corrected my question. Spoken instructions do not approve actions.</label>}
          <p id="evidence-sharing" className="text-sm leading-6 text-ink-secondary">Your bill fields, selected meter readings and question are sent to an external AI service. Leave out personal information. The original bill file is not sent again. <a className="ui-link underline underline-offset-4" href="https://developers.openai.com/api/docs/guides/your-data" target="_blank" rel="noopener noreferrer">Data policy</a></p>
          <label className="flex min-h-11 items-start gap-3 text-sm leading-6"><input id="evidence-sharing-consent" type="checkbox" required checked={share}
            aria-describedby="evidence-sharing" className="mt-1 size-4 shrink-0 accent-accent" onChange={event=>setShare(event.target.checked)}/>Allow AI to read this bill, these meter readings and my question.</label>
          <button className="ui-button ui-button-primary" disabled={busy||extracting||!billReviewed||!household||!share||!question.trim()||(fromVoice&&!voiceReviewed)}>{busy?'Comparing the evidence…':'Ask with bill and meter'}</button>
        </div>
      </fieldset>
    </form>
    <p role="status" aria-atomic="true" className="mt-3 text-sm leading-6 text-ink-secondary">{busy?'Checking the question and reading the selected evidence. No automatic retries.':answer?'Bill-and-meter answer ready below.':''}</p>
    {error && <p ref={alert} role="alert" tabIndex={-1} className="mt-3 rounded-lg border border-warning bg-warning-soft p-3 text-sm leading-6 text-warning focus-visible:outline-2 focus-visible:outline-warning">{error}</p>}
    {answer && <article aria-label="Bill-and-meter answer" className="mt-5 border-t border-rule pt-5">
      <h3 ref={answerHeading} tabIndex={-1} className="font-semibold focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-focus">Bill and meter answer</h3>
      <p className="mt-3 max-w-3xl whitespace-pre-wrap break-words text-sm leading-7">{answer}</p>
      <p className="mt-3 text-xs leading-5 text-muted">User-provided evidence remains unverified. No detector, real weather, utility tariff or state-changing tools were used.</p>
    </article>}
  </section>;
}
