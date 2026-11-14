import { afterEach, expect, it, vi } from 'vitest';
import { MeterClient } from './meter-import';
import { MAX_AUDIO_BYTES, parseTranscript } from './voice';

const transcript=()=>({text:'What does my water bill show?',duration_ms:1000,source:'audio_transcription',needs_review:true,request_id:'a'.repeat(36)});
const summary=()=>({context:{evidence_id:'meter_example',household_id:'house_example',origin:'user_provided',dataset_sha256:'a'.repeat(64),
  start:'2026-06-01T00:00:00Z',end_exclusive:'2026-06-01T00:15:00Z',reading_count:1,interval_minutes:15,volume_unit:'us_gallons',reading_type:'actual'},
  timezone:'UTC',total_us_gallons:'15.000000',inference_status:'not_enabled_for_imported_data',limitations:[]});
function clip(){const bytes=new Uint8Array(44);bytes.set([82,73,70,70]);bytes.set([87,65,86,69],8);return new File([bytes],'question.wav',{type:'audio/wav'});}
afterEach(()=>vi.unstubAllGlobals());

it('rejects unreviewable, missing, oversized and malformed transcripts before display',()=>{
  expect(parseTranscript(transcript())).toBe('What does my water bill show?');
  for(const patch of [{text:''},{text:'x'.repeat(2001)},{needs_review:false},{source:'verified'},
    {duration_ms:499},{duration_ms:30001},{duration_ms:1000.5},{request_id:'secret'}, {extra:true}]) {
    expect(()=>parseTranscript({...transcript(),...patch})).toThrow();
  }
});

it('shares only consented audio in the existing meter session without automatically answering',async()=>{
  const fetcher=vi.fn(async(path:string)=>path.endsWith('/sessions')?Response.json({session_token:'s'.repeat(43)}):
    path.endsWith('/meters/import')?Response.json(summary()):Response.json(transcript()));
  vi.stubGlobal('fetch',fetcher);
  const client=new MeterClient();
  await expect(client.transcribeVoice(clip(),false)).rejects.toThrow('Allow AI');
  await expect(client.transcribeVoice(new File(['x'],'question.mp3'),true)).rejects.toThrow('WAV');
  await expect(client.transcribeVoice(new File([new Uint8Array(MAX_AUDIO_BYTES+1)],'question.wav'),true)).rejects.toThrow('3 MiB');
  expect(fetcher).not.toHaveBeenCalled();
  await client.importFile(new File(['interval_start,volume\n2026-06-01T00:00:00Z,15'],'meter.csv'),
    {volume_unit:'us_gallons',interval_minutes:15,timezone:'UTC',reading_type:'actual'},true);
  expect(await client.transcribeVoice(clip(),true)).toBe(transcript().text);
  expect(fetcher).toHaveBeenCalledTimes(3);
  const options=(fetcher.mock.calls[2] as unknown as [string,RequestInit])[1];
  expect(options.credentials).toBe('omit');expect(options.cache).toBe('no-store');
  expect(options.headers).toMatchObject({Authorization:'Bearer '+'s'.repeat(43)});
  expect(Object.keys(JSON.parse(options.body as string)).sort()).toEqual(['data_base64','media_type','share_with_ai']);
  expect(fetcher.mock.calls.some(([path])=>path.includes('/agent/'))).toBe(false);
});

it('does not create or silently replace a missing voice session',async()=>{
  const fetcher=vi.fn();vi.stubGlobal('fetch',fetcher);
  await expect(new MeterClient().transcribeVoice(clip(),true)).rejects.toThrow('No active meter session');
  expect(fetcher).not.toHaveBeenCalled();
});
