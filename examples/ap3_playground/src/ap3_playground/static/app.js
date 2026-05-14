const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

function escapeHtml(s){return String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');}
function pretty(obj){return JSON.stringify(obj, null, 2);}

async function copyText(text){
  try{
    await navigator.clipboard.writeText(String(text ?? ''));
    setChat('Copied to clipboard.');
  }catch(_e){
    setChat('Copy failed (clipboard permission).');
  }
}

function labState(){
  const ops = (v) => v ? [v] : [];
  return {
    initiator: {
      role: $('#lab-i-role').value,
      supported_operations: ops($('#lab-i-ops').value),
      data_structure: $('#lab-i-structure').value,
      data_format: 'structured',
      data_freshness: $('#lab-i-freshness').value,
      industry: $('#lab-i-industry').value,
    },
    receiver: {
      role: $('#lab-r-role').value,
      supported_operations: ops($('#lab-r-ops').value),
      data_structure: $('#lab-r-structure').value,
      data_format: 'structured',
      data_freshness: $('#lab-r-freshness').value,
      industry: $('#lab-r-industry').value,
    }
  };
}

async function refreshCompat(){
  const body = { lab: labState() };
  const res = await fetch('/api/compat', {method:'POST', headers:{'content-type':'application/json'}, body: JSON.stringify(body)});
  const out = await res.json();
  const el = $('#lab-result');
  if (!out.ok){
    el.innerHTML = `<span class="bad">FAIL</span> ${escapeHtml(out.error || 'compat compute failed')}`;
    $('#btn-go-scenarios').disabled = true;
    return { compatible:false };
  }
  const cls = out.compatible ? 'ok' : 'bad';
  el.innerHTML = `<span class="${cls}">${out.compatible ? 'COMPATIBLE' : 'INCOMPATIBLE'}</span> score=${out.score.toFixed(2)} (min ${out.min_score})<div style="opacity:.85;margin-top:6px">${escapeHtml(out.explanation)}</div>`;
  $('#btn-go-scenarios').disabled = !out.compatible;
  return out;
}

async function refreshAgentCards(){
  const body = { lab: labState() };
  const res = await fetch('/api/agentcards', {method:'POST', headers:{'content-type':'application/json'}, body: JSON.stringify(body)});
  const out = await res.json();
  if (!out.ok){
    $('#lab-i-card-json').textContent = out.error || 'error';
    $('#lab-r-card-json').textContent = out.error || 'error';
    return;
  }
  console.log(out);
  $('#lab-i-card-json').textContent = pretty(out.initiator);
  $('#lab-r-card-json').textContent = pretty(out.receiver);
}

function setChat(msg){
  const el = document.createElement('div');
  el.className = 'bubble';
  el.textContent = msg;
  $('#chat-log').prepend(el);
}

function _refusalFromTrace(trace){
  const envs = trace?.envelopes || [];
  for (const e of envs){
    if ((e?.dir || '').includes('receiver -> initiator') && e?.phase === 'error' && e?.error){
      return e.error;
    }
  }
  // fallback: may appear only in result error text
  return null;
}

function renderOutcomeCard(trace){
  const el = $('#outcome-card');
  if (!el) return;
  if (!trace){
    el.innerHTML = `<div class="bubble">Run the walkthrough to see a result/refusal summary here.</div>`;
    return;
  }
  const refusal = _refusalFromTrace(trace);
  const ok = trace.result?.ok;
  if (walkthrough?.active && walkthrough.step < 4 && !refusal && ok !== false){
    el.innerHTML = `<div class="bubble">Outcome is produced at <b>Step 5</b> (after receiver processing completes).</div>`;
    return;
  }
  if (refusal){
    const hints = {
      "MISSING_INTENT": "Receiver expected `privacy_intent` on the first envelope.",
      "INTENT_SESSION_MISMATCH": "Receiver binds session_id: `intent.ap3_session_id` must equal `envelope.session_id`.",
      "WRONG_RECEIVER": "Receiver URL must appear in intent participants.",
      "BAD_SIGNATURE": "Receiver verified the intent signature with initiator public key.",
      "INTENT_REJECTED": "Intent directive failed validation (expiry/fields).",
      "INTENT_PAYLOAD_MISMATCH": "Receiver recomputed sha256(msg1_payload) and compared to intent.msg1_hash.",
      "REPLAY": "Receiver detected a replayed intent/msg1 using its replay cache.",
      "INCOMPATIBLE_PEER": "Receiver rejected based on compatibility policy.",
    };
    const hint = hints[refusal.error_code] || "";
    el.innerHTML = `<div class="bubble bad">
      <div><b>Receiver refused</b> <span style="opacity:.75">error_code=${escapeHtml(refusal.error_code || '')}</span></div>
      <div style="height:8px"></div>
      <div style="opacity:.9">${escapeHtml(refusal.error_message || '')}</div>
      ${hint ? `<div style="height:8px"></div><div style="opacity:.8">${escapeHtml(hint)}</div>` : ``}
      <div style="height:10px"></div>
      <div class="row">
        <button class="ghost" onclick="setActiveTab('envelope')">Open Envelope</button>
        <button class="ghost" onclick="setActiveTab('directives')">Open Directives</button>
        <button class="ghost" onclick="setActiveTab('audit')">Open Audit</button>
      </div>
    </div>`;
    return;
  }
  if (ok){
    const desc = trace.directives?.result?.result_data?.metadata?.description;
    let parsed = null;
    try{ parsed = desc ? JSON.parse(desc) : null; }catch(_e){}
    const isMatch = parsed?.is_match;
    const badge = (isMatch === true) ? '<span class="ok">MATCH</span>' : (isMatch === false ? '<span class="bad">NO MATCH</span>' : '<span class="ok">OK</span>');
    const input = trace?.psi_data?.initiator_input;
    const receiver = trace?.psi_data?.receiver_dataset || [];
    const meaning = (isMatch === true)
      ? "Customer appears in receiver's dataset (intersection exists)."
      : (isMatch === false ? "Customer does not appear in receiver's dataset (no intersection)." : "Protocol completed.");
    const matched = (isMatch === true) ? input : null;
    el.innerHTML = `<div class="bubble">
      <div><b>Outcome</b> ${badge}</div>
      <div style="height:8px"></div>
      <div style="opacity:.9">${escapeHtml(meaning)}</div>
      <div style="height:10px"></div>
      <div class="row">
        <div class="card">
          <div style="opacity:.8;margin:0 0 6px 2px;font-size:12px">initiator input</div>
          <pre>${escapeHtml(pretty({customer_data: input}))}</pre>
        </div>
        <div class="card">
          <div style="opacity:.8;margin:0 0 6px 2px;font-size:12px">receiver dataset</div>
          <pre>${escapeHtml(pretty({sanction_list: receiver}))}</pre>
        </div>
      </div>
      ${matched ? `<div style="height:10px"></div><div class="bubble http-ix2rx"><b>Matched record</b><div style="height:8px"></div><pre>${escapeHtml(pretty({record: matched}))}</pre></div>` : ``}
    </div>`;
    return;
  }
  el.innerHTML = `<div class="bubble bad"><b>Run failed</b><div style="height:8px"></div><pre>${escapeHtml(pretty(trace.result?.error || trace.result || {}))}</pre></div>`;
}

function setPanel(id, html){ $(id).innerHTML = html; }

function renderFlow(trace){
  const step = walkthrough?.active ? walkthrough.step : null;
  const stepTitle = (step != null) ? STEPS[step]?.title : 'Overview';
  const refusal = trace ? _refusalFromTrace(trace) : null;
  const code = {
    0: [
      "`PeerClient.resolve_peer()` → `_fetch_card()` (real AgentCard fetch)",
      "`extract_peer_info()` / AP3 extension decode",
    ],
    1: [
      "`CommitmentCompatibilityChecker.score_parameter_pair_compatibility()`",
    ],
    2: [
      "`PrivacyAgent.run_intent()` (start → build intent → envelope)",
      "`PrivacyAgent._build_signed_intent()` (signs `PrivacyIntentDirective`)",
      "`PeerClient.send_envelope()` (A2A JSON-RPC transport)",
    ],
    3: [
      "`PrivacyAgent.handle_envelope()` → `_handle_as_receiver()`",
      "Key checks (receiver): session binding, participants, signature verify, directive validate, msg1_hash bind, replay, compatibility",
      "`AP3Middleware._handle_as_receiver()` (middleware embedding path)",
    ],
    4: [
      "`PrivacyAgent.run_intent()` post-reply path",
      "`PrivacyAgent._build_signed_result()` (signs `PrivacyResultDirective`)",
    ],
    null: [
      "SDK entry points: `PrivacyAgent.serving()`, `PrivacyAgent.run_intent()`, `PrivacyAgent.handle_envelope()`",
      "Transport: `PeerClient.resolve_peer()` + `PeerClient.send_envelope()`",
    ],
  };
  const map = {
    0: { what: 'We fetch each agent’s AgentCard from its URL and decode the AP3 extension (roles, supported operations, commitments, public key).', go:'agentcard', label:'Open AgentCards' },
    1: { what: 'We run the compatibility scorer over both agents’ advertised AP3 parameters and explain why the pair is (in)compatible.', go:'audit', label:'Open Compatibility' },
    2: { what: 'Initiator signs a PrivacyIntentDirective (binding session_id + msg1 hash) and sends msg1 as a ProtocolEnvelope over A2A JSON-RPC. You can check the Envelope and Directives tabs to see the signed intent and envelope.', go:'a2ahttp', label:'Open A2A HTTP' },
    3: { what: 'Receiver validates session binding, signature, directive validity, msg1 hash, replay protection and sends back msg2 as a ProtocolEnvelope over A2A JSON-RPC. You can check the Envelope also to see the signed envelope.', go:'audit', label:'Open Receiver checks' },
    4: { what: 'Initiator processes the receiver reply and produces a signed PrivacyResultDirective (result + proofs).', go:'directives', label:'Open Directives' },
    null: { what: 'Use the walkthrough to run AP3 step-by-step. The inspector tabs show raw HTTP, envelopes, directives, audit checks, and logs.', go:'', label:'' },
  };
  const info = map[step] || map[null];
  const pointers = (code[step] || code[null] || []).map(x => `<li>${escapeHtml(x)}</li>`).join('');

  const errorToAudit = {
    "MISSING_INTENT": "rx.check.missing_intent",
    "INTENT_SESSION_MISMATCH": "rx.check.session_binding",
    "WRONG_RECEIVER": "rx.check.participants",
    "BAD_SIGNATURE": "rx.check.signature",
    "INTENT_REJECTED": "rx.check.directive_validate",
    "INTENT_PAYLOAD_MISMATCH": "rx.check.msg1_hash",
    "REPLAY": "rx.check.replay_key",
    "INCOMPATIBLE_PEER": "rx.check.compatibility",
  };
  const failingAuditName = refusal?.error_code ? (errorToAudit[refusal.error_code] || null) : null;
  const auditEvent = failingAuditName ? (trace?.audit || []).find(e => e?.name === failingAuditName) : null;

  if (refusal){
    const hints = {
      "MISSING_INTENT": "Receiver expected `privacy_intent` on the first envelope.",
      "INTENT_SESSION_MISMATCH": "Receiver binds session_id: `intent.ap3_session_id` must equal `envelope.session_id`.",
      "WRONG_RECEIVER": "Receiver URL must appear in intent participants.",
      "BAD_SIGNATURE": "Receiver verified the intent signature with initiator public key.",
      "INTENT_REJECTED": "Intent directive failed validation (expiry/fields).",
      "INTENT_PAYLOAD_MISMATCH": "Receiver recomputed sha256(msg1_payload) and compared to intent.msg1_hash.",
      "REPLAY": "Receiver detected a replayed intent/msg1 using its replay cache.",
      "INCOMPATIBLE_PEER": "Receiver rejected based on compatibility policy.",
    };
    const hint = hints[refusal.error_code] || "";
    const auditHtml = auditEvent
      ? `<div style="height:10px"></div>
         <div style="opacity:.85;font-size:12px;font-weight:700">Relevant receiver check</div>
         <div class="bubble" style="margin-top:8px">
           <div><span class="bad">FAIL</span> <b>${escapeHtml(auditEvent.name || '')}</b></div>
           <pre style="margin-top:8px">${escapeHtml(pretty(auditEvent.details || {}))}</pre>
         </div>`
      : '';
    setPanel('#panel-flow', `
      <div class="bubble bad">
        <div style="font-weight:800;margin-bottom:6px">Why refused</div>
        <div><b>Receiver refused</b> <span style="opacity:.75">error_code=${escapeHtml(refusal.error_code || '')}</span></div>
        <div style="height:8px"></div>
        <div style="opacity:.92">${escapeHtml(refusal.error_message || '')}</div>
        ${hint ? `<div style="height:8px"></div><div style="opacity:.85">${escapeHtml(hint)}</div>` : ``}
        <div style="height:10px"></div>
        <div class="row">
          <button class="ghost" onclick="setActiveTab('envelope')">Open Envelope</button>
          <button class="ghost" onclick="setActiveTab('directives')">Open Directives</button>
          <button class="ghost" onclick="setActiveTab('audit')">Open Audit</button>
          <button class="ghost" onclick="setActiveTab('a2ahttp')">Open A2A HTTP</button>
        </div>
      </div>
      ${auditHtml}
    `);
    return;
  }

  setPanel('#panel-flow', `
    <div class="bubble">
      <div style="font-weight:800;margin-bottom:6px">Flow — ${escapeHtml(stepTitle || 'Overview')}</div>
      <div style="opacity:.9">${escapeHtml(info.what)}</div>
      <div style="height:10px"></div>
      ${info.go ? `<button onclick="setActiveTab('${info.go}')">${escapeHtml(info.label)}</button>` : ''}
    </div>
    ${info.go ? `
    <details class="bubble" open>
      <summary style="cursor:pointer;font-weight:700">Code pointers (what runs)</summary>
      <div style="height:10px"></div>
      <div style="opacity:.85;font-size:12px;line-height:1.5">
        This is a “map” of the main functions involved. It’s meant to help you jump into the SDK quickly,
        but it can be noisy if you’re just trying to learn the concepts.
      </div>
      <div style="height:10px"></div>
      <ul style="margin:0;padding-left:18px;opacity:.95;line-height:1.6">${pointers}</ul>
    </details>` : ''}
  `);
}

function renderRequest(trace){
  const r = trace.request || {};
  setPanel('#panel-request', `
    <div class="kv">
      <div>method</div><div>${escapeHtml(r.method || '')}</div>
      <div>path</div><div>${escapeHtml(r.path || '')}</div>
    </div>
    <div style="height:10px"></div>
    <div class="row">
      <div class="card">
        <div style="opacity:.8;margin:0 0 6px 2px;font-size:12px">headers</div>
        <pre>${escapeHtml(pretty(r.headers || {}))}</pre>
      </div>
      <div class="card">
        <div style="opacity:.8;margin:0 0 6px 2px;font-size:12px">body</div>
        <pre>${escapeHtml(pretty(r.body || {}))}</pre>
      </div>
    </div>
    <div style="height:10px"></div>
    <div style="opacity:.8;margin:0 0 6px 2px;font-size:12px">copy-as-curl</div>
    <div class="row" style="align-items:center">
      <div style="opacity:.8;margin:0 0 6px 2px;font-size:12px;flex:1">copy-as-curl</div>
      <button class="ghost" onclick="copyText(${JSON.stringify(r.curl || '')})">Copy</button>
    </div>
    <pre>${escapeHtml(r.curl || '')}</pre>
  `);
}

function renderA2AHttp(trace){
  const entries = trace.a2a_http || [];
  if (!entries.length){
    setPanel('#panel-a2ahttp', `<div class="bubble">No captured A2A HTTP traffic (this run may have failed before network calls).</div>`);
    return;
  }
  const html = entries.map((e) => {
    const isReq = e.type === 'request';
    const dir = e.dir || (String(e.url || '').includes(':18083') ? 'initiator → receiver' : (String(e.url || '').includes(':18082') ? 'receiver → initiator' : ''));
    const cls = (dir.includes('initiator') ? 'http-ix2rx' : (dir.includes('receiver') ? 'http-rx2ix' : ''));
    const badge = isReq ? '<span class="ok">REQ</span>' : `<span class="${(e.status_code>=200 && e.status_code<300)?'ok':'bad'}">RES ${e.status_code}</span>`;
    const line = isReq ? `${e.method} ${e.url}` : `${e.url}`;
    const h = e.headers || {};
    const body = e.body || '';
    const dirBadge = dir ? `<span style="opacity:.75;margin-left:8px">${escapeHtml(dir)}</span>` : '';
    return `<div class="bubble ${cls}">
      <div>${badge} <b>${escapeHtml(line)}</b>${dirBadge} <span style="opacity:.6">${escapeHtml(e.ts || '')}</span></div>
      <div style="height:8px"></div>
      <div style="opacity:.8;margin:0 0 6px 2px;font-size:12px">headers</div>
      <pre>${escapeHtml(pretty(h))}</pre>
      <div style="height:8px"></div>
      <div style="opacity:.8;margin:0 0 6px 2px;font-size:12px">body</div>
      <pre>${escapeHtml(body)}</pre>
    </div>`;
  }).join('');
  setPanel('#panel-a2ahttp', html);
}

function renderAgentCard(trace){
  const i = trace.agent_cards?.initiator || {};
  const r = trace.agent_cards?.receiver || {};
  setPanel('#panel-agentcard', `
    <div class="row">
      <div class="card">
        <details open>
          <summary style="cursor:pointer;font-weight:700">Initiator — AP3 extension</summary>
          <div style="height:10px"></div>
          <pre>${escapeHtml(pretty(i.ap3_extension || {}))}</pre>
        </details>
      </div>
      <div class="card">
        <details open>
          <summary style="cursor:pointer;font-weight:700">Receiver — AP3 extension</summary>
          <div style="height:10px"></div>
          <pre>${escapeHtml(pretty(r.ap3_extension || {}))}</pre>
        </details>
      </div>
    </div>
  `);
}

function decodeAp3ExtFromCard(card){
  try{
    const exts = card?.capabilities?.extensions || [];
    for (const e of exts){
      if (e?.uri && String(e.uri).includes('ap3')){
        return e.params || null;
      }
    }
  }catch(_e){}
  return null;
}

async function walkthroughPrefetchDiscovery(){
  const body = { lab: labState() };
  const res = await fetch('/api/agentcards', {method:'POST', headers:{'content-type':'application/json'}, body: JSON.stringify(body)});
  const out = await res.json();
  if (!out.ok){
    setPanel('#panel-agentcard', `<div class="bubble"><span class="bad">FAIL</span> ${escapeHtml(out.error || 'agentcards failed')}</div>`);
    return;
  }
  const trace = {
    agent_cards: {
      initiator: { card: out.initiator, ap3_extension: decodeAp3ExtFromCard(out.initiator) },
      receiver: { card: out.receiver, ap3_extension: decodeAp3ExtFromCard(out.receiver) },
    }
  };
  window.__discoveryTrace = trace;
  renderAgentCard(trace);
}

async function walkthroughPrefetchCompat(){
  const body = { lab: labState() };
  const res = await fetch('/api/compat', {method:'POST', headers:{'content-type':'application/json'}, body: JSON.stringify(body)});
  const out = await res.json();
  if (!out.ok){
    setPanel('#panel-audit', `<div class="bubble"><span class="bad">FAIL</span> ${escapeHtml(out.error || 'compat failed')}</div>`);
    return;
  }
  const cls = out.compatible ? 'ok' : 'bad';
  setPanel('#panel-audit', `<div class="bubble"><div><span class="${cls}">${out.compatible ? 'COMPATIBLE' : 'INCOMPATIBLE'}</span> <b>compatibility preflight</b></div><pre style="margin-top:8px">${escapeHtml(pretty(out))}</pre></div>`);
}

function renderEnvelopes(trace){
  const envs = trace.envelopes || [];
  const inc = envs.filter(e => (e?.dir || '').includes('initiator -> receiver'));
  const out = envs.filter(e => (e?.dir || '').includes('receiver -> initiator'));
  const hasRefusal = !!_refusalFromTrace(trace);
  const hideRxToIx = (walkthrough?.active && walkthrough.step === 2 && !hasRefusal); // hide only on happy path
  setPanel('#panel-envelope', `
    <div class="row">
      <div class="card">
        <div style="font-weight:700;margin-bottom:6px">Initiator → Receiver</div>
        <pre>${escapeHtml(pretty(inc))}</pre>
      </div>
      ${
        hideRxToIx
          ? `<div class="card"><div style="font-weight:700;margin-bottom:6px">Receiver → Initiator</div><div class="bubble">Not available yet (finish receiver checks to produce a reply).</div></div>`
          : `<div class="card"><div style="font-weight:700;margin-bottom:6px">Receiver → Initiator</div><pre>${escapeHtml(pretty(out))}</pre></div>`
      }
    </div>
  `);
}

function renderDirectives(trace){
  const d = trace.directives || {};
  const hideResult = walkthrough?.active && walkthrough.step === 2; // Step 3 (1-based): Send msg1
  setPanel('#panel-directives', `
    <div class="row">
      <div class="card">
        <div style="font-weight:700;margin-bottom:6px">Intent directive</div>
        <button class="ghost" style="margin:-4px 0 8px" onclick="copyText(${JSON.stringify(pretty(d.intent || {}))})">Copy JSON</button>
        <pre>${escapeHtml(pretty(d.intent || {}))}</pre>
        <div style="height:10px"></div>
        <div style="opacity:.8;margin:0 0 6px 2px;font-size:12px">canonical + signature</div>
        <button class="ghost" style="margin:-4px 0 8px" onclick="copyText(${JSON.stringify(pretty(d.intent_canonical || {}))})">Copy canonical</button>
        <pre>${escapeHtml(pretty(d.intent_canonical || {}))}</pre>
      </div>
      ${
        hideResult
          ? `<div class="card"><div style="font-weight:700;margin-bottom:6px">Result directive</div><div class="bubble">Not available yet (result is produced after receiver processing completes).</div></div>`
          : `<div class="card">
              <div style="font-weight:700;margin-bottom:6px">Result directive</div>
              <button class="ghost" style="margin:-4px 0 8px" onclick="copyText(${JSON.stringify(pretty(d.result || {}))})">Copy JSON</button>
              <pre>${escapeHtml(pretty(d.result || {}))}</pre>
              <div style="height:10px"></div>
              <div style="opacity:.8;margin:0 0 6px 2px;font-size:12px">canonical + signature</div>
              <button class="ghost" style="margin:-4px 0 8px" onclick="copyText(${JSON.stringify(pretty(d.result_canonical || {}))})">Copy canonical</button>
              <pre>${escapeHtml(pretty(d.result_canonical || {}))}</pre>
            </div>`
      }
    </div>
  `);
}

function renderAudit(trace){
  const a = trace.audit || [];
  const rows = a.map(e => {
    const cls = e.ok ? 'ok' : 'bad';
    return `<div class="bubble"><div><span class="${cls}">${e.ok ? 'OK' : 'FAIL'}</span> <b>${escapeHtml(e.name)}</b> <span style="opacity:.6">+${e.ts_ms}ms</span></div><pre style="margin-top:8px">${escapeHtml(pretty(e.details || {}))}</pre></div>`;
  }).join('');
  setPanel('#panel-audit', rows || `<div class="bubble">No audit events.</div>`);
}

function renderLogs(trace){
  setPanel('#panel-logs', `<pre>${escapeHtml(pretty(trace.logs || []))}</pre>`);
}

function renderAll(trace){
  window.__lastTrace = trace;
  renderPsiDataPanel(trace);
  renderOutcomeCard(trace);
  renderFlow(trace);
  renderA2AHttp(trace);
  renderAgentCard(trace);
  renderEnvelopes(trace);
  renderDirectives(trace);
  renderAudit(trace);
  renderLogs(trace);

  const ok = trace.result?.ok;
  if (ok) setChat(`Result: OK`);
  else setChat(`Result: ERROR — ${pretty(trace.result?.error || trace.result)}`);
}

function attackState(){
  return {
    tamper_session_id: $('#atk-session-id')?.checked || false,
    tamper_participants: $('#atk-participants')?.checked || false,
    tamper_msg1_payload: $('#atk-msg1')?.checked || false,
    psi_outcome: ($('#psi-fail')?.checked ? 'unsuccessful' : 'successful'),
  };
}

function renderPsiDataPanel(fromTrace){
  const receiver = (fromTrace?.psi_data?.receiver_dataset) || [
    "Jane Smith,S001,456 Elm St",
    "Bob Brown,S002,789 Oak Ave",
  ];
  const initiator = (fromTrace?.psi_data?.initiator_input) || (
    ($('#psi-fail')?.checked)
      ? "No Match,N000,0 Nowhere Rd"
      : "Jane Smith,S001,456 Elm St"
  );
  const el = $('#psi-data');
  if (!el) return;
  el.innerHTML = `
    <details open class="quick-scenarios" style="margin:10px 0 0">
      <summary>Data being matched (PSI)</summary>
      <div class="controls" style="display:block">
        <div class="row">
          <div class="card">
            <div style="font-weight:700;margin-bottom:6px">Initiator input</div>
            <pre>${escapeHtml(pretty({customer_data: initiator}))}</pre>
          </div>
          <div class="card">
            <div style="font-weight:700;margin-bottom:6px">Receiver dataset</div>
            <pre>${escapeHtml(pretty({sanction_list: receiver}))}</pre>
          </div>
        </div>
      </div>
    </details>
  `;
}

async function runScenario(scenario){
  const compat = await refreshCompat();
  if (!compat.compatible && scenario === 'psi'){
    setChat(`Compatibility lab says INCOMPATIBLE; still running to show refusal.`);
  }
  setChat(`Running: ${scenario}`);
  const res = await fetch('/api/run', {method:'POST', headers:{'content-type':'application/json'}, body: JSON.stringify({scenario, lab: labState(), attacks: attackState()})});
  const trace = await res.json();
  renderAll(trace);
}

// ---------------- Walkthrough mode ----------------
let walkthrough = { active:false, step:0, trace:null, walk_id:null };
const STEPS = [
  { title:'Discovery', text:'Fetch AgentCards and read AP3 extension (roles/ops/commitments/public key).', tab:'agentcard' },
  { title:'Compatibility', text:'Compute compatibility score + explanation (roles, common ops, commitment pairing).', tab:'audit' },
  { title:'Send msg1', text:'Send ProtocolEnvelope msg1 over A2A JSON-RPC (inspect raw HTTP).', tab:'a2ahttp' },
  { title:'Receiver checks', text:'Receiver validates session binding, participants, signature, msg1_hash, replay.', tab:'audit' },
  { title:'Result', text:'Initiator produces and signs PrivacyResultDirective.', tab:'directives' },
];

function setActiveTab(tab){
  const t = $(`.tab[data-tab="${tab}"]`);
  if (!t) return;
  $$('.tab').forEach(x => x.classList.remove('active'));
  $$('.tab-panel').forEach(x => x.classList.remove('active'));
  t.classList.add('active');
  $('#panel-' + tab).classList.add('active');
}

function updateWalkthroughUI(){
  const stepEl = $('#walkthrough-step');
  if (!walkthrough.active){
    $('#btn-walkthrough-prev').disabled = true;
    $('#btn-walkthrough-next').disabled = true;
    $('#btn-walkthrough-start').disabled = false;
    $('#btn-walkthrough-reset').style.display = 'none';
    stepEl.textContent = 'Not started.';
    return;
  }
  const s = STEPS[walkthrough.step];
  $('#btn-walkthrough-start').disabled = true;
  $('#btn-walkthrough-prev').disabled = walkthrough.step === 0;
  const hasErr = !!(walkthrough?.trace && (_refusalFromTrace(walkthrough.trace) || walkthrough.trace?.result?.ok === false));
  $('#btn-walkthrough-next').disabled = hasErr || walkthrough.step >= STEPS.length - 1;
  $('#btn-walkthrough-reset').style.display = 'inline-block';
  stepEl.innerHTML = `<b>Step ${walkthrough.step+1}/${STEPS.length}: ${escapeHtml(s.title)}</b><div style="opacity:.9;margin-top:6px">${escapeHtml(s.text)}</div>`;
  setActiveTab('flow');

  // Apply step-dependent hide/show (receiver card) even if trace already rendered.
  const t = window.__lastTrace || window.__discoveryTrace;
  if (t){
    renderAgentCard(t);
    renderEnvelopes(t);
    renderDirectives(t);
    renderFlow(t);
  }
}

function resetWalkthrough(){
  walkthrough = { active:false, step:0, trace:null, walk_id: walkthrough.walk_id };
  window.__lastTrace = null;
  window.__discoveryTrace = null;
  $('#chat-log').innerHTML = '';
  ['#panel-flow','#panel-request','#panel-a2ahttp','#panel-agentcard','#panel-envelope','#panel-directives','#panel-audit','#panel-logs']
    .forEach(id => { const el = $(id); if (el) el.innerHTML = ''; });
  fetch('/api/walkthrough/reset', {method:'POST', headers:{'content-type':'application/json'}, body: JSON.stringify({})}).then(r=>r.json()).then(j=>{ walkthrough.walk_id = j.walk_id; }).catch(()=>{});
  renderPsiDataPanel();
  renderOutcomeCard(null);
  renderFlow(null);
  updateWalkthroughUI();
}

async function startWalkthrough(){
  walkthrough.active = true;
  walkthrough.step = 0;
  walkthrough.trace = null;
  setChat('Walkthrough started. Click Next to proceed step-by-step.');
  if (!walkthrough.walk_id){
    const r = await fetch('/api/walkthrough/reset', {method:'POST', headers:{'content-type':'application/json'}, body: JSON.stringify({})});
    const j = await r.json();
    walkthrough.walk_id = j.walk_id;
  }
  // Prefetch step 1 content without running the protocol.
  await walkthroughPrefetchDiscovery();
  renderPsiDataPanel();
  renderOutcomeCard(null);
  renderFlow(null);
  updateWalkthroughUI();
}

function showView(which){
  $('#view-landing')?.classList.toggle('view-active', which === 'landing');
  $('#view-lab').classList.toggle('view-active', which === 'lab');
  $('#view-playground').classList.toggle('view-active', which === 'playground');
}

$('#btn-go-lab')?.addEventListener('click', () => showView('lab'));
$('#btn-go-scenarios').addEventListener('click', async () => {
  const c = await refreshCompat();
  if (!c.compatible) return;
  showView('playground');
});
$('#btn-go-scenarios-anyway')?.addEventListener('click', () => showView('playground'));
$('#btn-back-lab').addEventListener('click', () => showView('lab'));

$('#btn-walkthrough-start')?.addEventListener('click', startWalkthrough);
$('#btn-walkthrough-reset')?.addEventListener('click', resetWalkthrough);
$('#btn-walkthrough-next')?.addEventListener('click', async () => {
  walkthrough.step = Math.min(STEPS.length-1, walkthrough.step+1);

  // Step 2: compatibility preflight (no protocol run).
  if (walkthrough.step === 1){
    await walkthroughPrefetchCompat();
  }

  // Step 3: send msg1 (no finalize).
  if (walkthrough.step === 2){
    setChat('Walkthrough: sending msg1 (initiator → receiver)…');
    const res = await fetch('/api/walkthrough/send_msg1', {method:'POST', headers:{'content-type':'application/json'}, body: JSON.stringify({walk_id: walkthrough.walk_id, lab: labState(), attacks: attackState()})});
    const trace = await res.json();
    walkthrough.trace = trace;
    renderAll(trace);
  }

  // Step 4: show receiver checks (no finalize).
  if (walkthrough.step === 3){
    setChat('Walkthrough: receiver checks…');
    const res = await fetch('/api/walkthrough/receiver_checks', {method:'POST', headers:{'content-type':'application/json'}, body: JSON.stringify({walk_id: walkthrough.walk_id})});
    const trace = await res.json();
    walkthrough.trace = trace;
    renderAll(trace);
  }

  // Step 5: finalize result (initiator processes reply).
  if (walkthrough.step === 4){
    setChat('Walkthrough: finalizing (initiator processes reply)…');
    const res = await fetch('/api/walkthrough/finalize', {method:'POST', headers:{'content-type':'application/json'}, body: JSON.stringify({walk_id: walkthrough.walk_id})});
    const trace = await res.json();
    walkthrough.trace = trace;
    renderAll(trace);
  }

  updateWalkthroughUI();
});
$('#btn-walkthrough-prev')?.addEventListener('click', () => { walkthrough.step = Math.max(0, walkthrough.step-1); updateWalkthroughUI(); });

$$('.controls button').forEach(b => b.addEventListener('click', () => runScenario(b.dataset.scenario)));
$$('.tab').forEach(t => t.addEventListener('click', () => {
  $$('.tab').forEach(x => x.classList.remove('active'));
  $$('.tab-panel').forEach(x => x.classList.remove('active'));
  t.classList.add('active');
  $('#panel-' + t.dataset.tab).classList.add('active');
}));

// Recompute on lab changes.
['#lab-i-role','#lab-i-ops','#lab-i-structure','#lab-i-freshness','#lab-i-industry',
 '#lab-r-role','#lab-r-ops','#lab-r-structure','#lab-r-freshness','#lab-r-industry'
].forEach(id => $(id).addEventListener('change', async () => { await refreshCompat(); await refreshAgentCards(); }));

// initial
refreshCompat();
refreshAgentCards();
renderPsiDataPanel();
renderOutcomeCard(null);
renderFlow(null);

['#psi-success', '#psi-fail'].forEach(id => $(id)?.addEventListener('change', () => renderPsiDataPanel()));

