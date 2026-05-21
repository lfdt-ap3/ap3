const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

function escapeHtml(s){return String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');}
function escapeAttr(s){return String(s).replaceAll('&','&amp;').replaceAll('"','&quot;').replaceAll("'", '&#39;').replaceAll('<','&lt;').replaceAll('>','&gt;');}
function pretty(obj){return JSON.stringify(obj, null, 2);}

// Collapsible JSON tree. Returns an HTML string.
// `depth` controls auto-collapse: nested objects beyond depth 1 start closed.
function jsonTree(value, depth = 0){
  const t = typeof value;
  if (value === null) return `<span class="j-null">null</span>`;
  if (t === 'boolean') return `<span class="j-bool">${value}</span>`;
  if (t === 'number') return `<span class="j-num">${value}</span>`;
  if (t === 'string'){
    // Long base64-ish strings get truncated with a click-to-expand.
    if (value.length > 200){
      const head = value.slice(0, 80);
      return `<span class="j-str" title="${escapeAttr(value)}">"${escapeHtml(head)}<span class="j-ellipsis">…(${value.length - head.length} more chars)</span>"</span>`;
    }
    return `<span class="j-str">"${escapeHtml(value)}"</span>`;
  }
  if (Array.isArray(value)){
    if (value.length === 0) return `<span class="j-bracket">[]</span>`;
    const open = depth < 1;
    const inner = value.map((v, i) => `<div class="j-row"><span class="j-idx">${i}:</span> ${jsonTree(v, depth + 1)}</div>`).join('');
    return `<details class="j-block" ${open ? 'open' : ''}><summary><span class="j-bracket">[</span><span class="j-meta">${value.length} item${value.length === 1 ? '' : 's'}</span><span class="j-bracket">]</span></summary><div class="j-children">${inner}</div></details>`;
  }
  if (t === 'object'){
    const keys = Object.keys(value);
    if (keys.length === 0) return `<span class="j-bracket">{}</span>`;
    const open = depth < 1;
    const inner = keys.map(k => `<div class="j-row"><span class="j-key">${escapeHtml(k)}</span><span class="j-colon">:</span> ${jsonTree(value[k], depth + 1)}</div>`).join('');
    return `<details class="j-block" ${open ? 'open' : ''}><summary><span class="j-bracket">{</span><span class="j-meta">${keys.length} key${keys.length === 1 ? '' : 's'}</span><span class="j-bracket">}</span></summary><div class="j-children">${inner}</div></details>`;
  }
  return `<span class="j-str">${escapeHtml(String(value))}</span>`;
}

// Produces a button that copies arbitrary text via a delegated listener
// (see bottom of file). Using a data-attribute avoids the HTML-attribute
// quote-escaping landmine that inline onclick="..." has with JSON strings.
function copyButton(text, label = 'Copy', className = 'ghost'){
  return `<button type="button" class="${className}" data-copy-payload="${escapeAttr(String(text ?? ''))}">${escapeHtml(label)}</button>`;
}

// Wraps a jsonTree with a copy button.
function jsonTreeBlock(value, opts = {}){
  const raw = pretty(value);
  const copyHtml = opts.copy !== false ? copyButton(raw, 'Copy JSON', 'ghost j-copy') : '';
  return `<div class="j-wrap">${copyHtml}<div class="json-tree">${jsonTree(value)}</div></div>`;
}

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

const REFUSAL_HINTS = {
  "MISSING_INTENT":           { hint: "Receiver expected `privacy_intent` on the first envelope.",                                 audit: "rx.check.missing_intent" },
  "INTENT_SESSION_MISMATCH":  { hint: "Receiver binds session_id: `intent.ap3_session_id` must equal `envelope.session_id`.",      audit: "rx.check.session_binding" },
  "WRONG_RECEIVER":           { hint: "Receiver URL must appear in intent participants.",                                          audit: "rx.check.participants" },
  "BAD_SIGNATURE":            { hint: "Receiver verified the intent signature with initiator public key.",                         audit: "rx.check.signature" },
  "INTENT_REJECTED":          { hint: "Intent directive failed validation (expiry/fields).",                                       audit: "rx.check.directive_validate" },
  "INTENT_PAYLOAD_MISMATCH":  { hint: "Receiver recomputed sha256(envelope.payload) and compared to intent.payload_hash.",         audit: "rx.check.payload_hash" },
  "REPLAY":                   { hint: "Receiver detected a replayed intent using its replay cache.",                               audit: "rx.check.replay_key" },
  "INCOMPATIBLE_PEER":        { hint: "Receiver rejected based on compatibility policy.",                                          audit: "rx.check.compatibility" },
};

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
    const hint = REFUSAL_HINTS[refusal.error_code]?.hint || "";
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
        <button class="ghost" onclick="setActiveTab('refusals')">All refusal codes</button>
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
      "Key checks (receiver): session binding, participants, signature verify, directive validate, payload_hash bind, replay, compatibility",
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
    2: { what: 'Initiator signs a PrivacyIntentDirective (binding session_id + payload hash) and sends the first envelope as a ProtocolEnvelope over A2A JSON-RPC. You can check the Envelope and Directives tabs to see the signed intent and envelope.', go:'a2ahttp', label:'Open A2A HTTP' },
    3: { what: 'Receiver validates session binding, signature, directive validity, payload hash, replay protection and sends back its reply as a ProtocolEnvelope over A2A JSON-RPC. You can check the Envelope also to see the signed envelope.', go:'audit', label:'Open Receiver checks' },
    4: { what: 'Initiator processes the receiver reply and produces a signed PrivacyResultDirective (result + proofs).', go:'directives', label:'Open Directives' },
    null: { what: 'Use the walkthrough to run AP3 step-by-step. The inspector tabs show raw HTTP, envelopes, directives, audit checks, and logs.', go:'', label:'' },
  };
  const info = map[step] || map[null];
  const pointers = (code[step] || code[null] || []).map(x => `<li>${escapeHtml(x)}</li>`).join('');

  const failingAuditName = refusal?.error_code ? (REFUSAL_HINTS[refusal.error_code]?.audit || null) : null;
  const auditEvent = failingAuditName ? (trace?.audit || []).find(e => e?.name === failingAuditName) : null;

  if (refusal){
    const hint = REFUSAL_HINTS[refusal.error_code]?.hint || "";
    const auditHtml = auditEvent
      ? `<div style="height:10px"></div>
         <div style="opacity:.85;font-size:12px;font-weight:700">Relevant receiver check</div>
         <div class="bubble" style="margin-top:8px">
           <div><span class="bad">FAIL</span> <b>${escapeHtml(auditEvent.name || '')}</b></div>
           <div style="height:8px"></div>${jsonTreeBlock(auditEvent.details || {}, {copy: false})}
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
      <div style="font-size:11px;text-transform:uppercase;letter-spacing:.5px;opacity:.7;margin-bottom:4px">Concept</div>
      <div style="font-weight:800;margin-bottom:6px">Flow — ${escapeHtml(stepTitle || 'Overview')}</div>
      <div style="opacity:.92;line-height:1.55">${escapeHtml(info.what)}</div>
      <div style="height:10px"></div>
      ${info.go ? `<button onclick="setActiveTab('${info.go}')">${escapeHtml(info.label)}</button>` : ''}
    </div>
    ${pointers ? `
    <details class="bubble">
      <summary style="cursor:pointer;font-weight:700">
        <span style="font-size:11px;text-transform:uppercase;letter-spacing:.5px;opacity:.7;font-weight:600">For engineers</span>
        &nbsp;&middot;&nbsp; Show me the code (SDK pointers)
      </summary>
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
      ${copyButton(r.curl || '', 'Copy')}
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
    // body may be a JSON string we can pretty-tree, or plain text.
    let bodyHtml;
    try {
      const parsed = (typeof body === 'string' && body.trim().startsWith('{')) ? JSON.parse(body) : null;
      bodyHtml = parsed !== null ? jsonTreeBlock(parsed, {copy: false}) : `<pre>${escapeHtml(body)}</pre>`;
    } catch(_e) {
      bodyHtml = `<pre>${escapeHtml(body)}</pre>`;
    }
    return `<div class="bubble ${cls}">
      <div>${badge} <b>${escapeHtml(line)}</b>${dirBadge} <span style="opacity:.6">${escapeHtml(e.ts || '')}</span></div>
      <div style="height:8px"></div>
      <details>
        <summary style="cursor:pointer;opacity:.8;font-size:12px">headers</summary>
        <div style="height:6px"></div>
        ${jsonTreeBlock(h, {copy: false})}
      </details>
      <div style="height:8px"></div>
      <div style="opacity:.8;margin:0 0 6px 2px;font-size:12px">body</div>
      ${bodyHtml}
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
        <div style="font-weight:700;margin-bottom:6px">Initiator — AP3 extension</div>
        ${jsonTreeBlock(i.ap3_extension || {})}
      </div>
      <div class="card">
        <div style="font-weight:700;margin-bottom:6px">Receiver — AP3 extension</div>
        ${jsonTreeBlock(r.ap3_extension || {})}
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
  setPanel('#panel-audit', `<div class="bubble"><div><span class="${cls}">${out.compatible ? 'COMPATIBLE' : 'INCOMPATIBLE'}</span> <b>compatibility preflight</b></div><div style="height:8px"></div>${jsonTreeBlock(out, {copy: false})}</div>`);
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
        ${jsonTreeBlock(inc)}
      </div>
      ${
        hideRxToIx
          ? `<div class="card"><div style="font-weight:700;margin-bottom:6px">Receiver → Initiator</div><div class="bubble">Not available yet (finish receiver checks to produce a reply).</div></div>`
          : `<div class="card"><div style="font-weight:700;margin-bottom:6px">Receiver → Initiator</div>${jsonTreeBlock(out)}</div>`
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
        ${jsonTreeBlock(d.intent || {})}
        <div style="height:10px"></div>
        <div style="opacity:.8;margin:0 0 6px 2px;font-size:12px">canonical + signature</div>
        ${jsonTreeBlock(d.intent_canonical || {})}
      </div>
      ${
        hideResult
          ? `<div class="card"><div style="font-weight:700;margin-bottom:6px">Result directive</div><div class="bubble">Not available yet (result is produced after receiver processing completes).</div></div>`
          : `<div class="card">
              <div style="font-weight:700;margin-bottom:6px">Result directive</div>
              ${jsonTreeBlock(d.result || {})}
              <div style="height:10px"></div>
              <div style="opacity:.8;margin:0 0 6px 2px;font-size:12px">canonical + signature</div>
              ${jsonTreeBlock(d.result_canonical || {})}
            </div>`
      }
    </div>
  `);
}

function renderAudit(trace){
  const a = trace.audit || [];
  const rows = a.map(e => {
    const cls = e.ok ? 'ok' : 'bad';
    return `<div class="bubble"><div><span class="${cls}">${e.ok ? 'OK' : 'FAIL'}</span> <b>${escapeHtml(e.name)}</b> <span style="opacity:.6">+${e.ts_ms}ms</span></div><div style="height:8px"></div>${jsonTreeBlock(e.details || {}, {copy: false})}</div>`;
  }).join('');
  setPanel('#panel-audit', rows || `<div class="bubble">No audit events.</div>`);
}

function renderLogs(trace){
  setPanel('#panel-logs', jsonTreeBlock(trace.logs || []));
}

function renderPsi(trace){
  const pi = trace?.psi_internals || null;
  if (!pi || !pi.rounds || !pi.rounds.length){
    setPanel('#panel-psi', `<div class="bubble">No PSI internals yet &mdash; run the walkthrough to produce protocol rounds.</div>`);
    return;
  }
  const intro = `
    <div class="bubble">
      <div style="font-weight:700;margin-bottom:6px">PSI wire-level decode</div>
      <div style="opacity:.92;line-height:1.55">
        Each PSI round carries a base64-encoded payload. Below is the structural breakdown of
        what the bytes actually contain. <b>The customer record never appears here</b> &mdash; it's
        hashed and blinded into the Ristretto255 group elements inside <code>psc_msg1</code>.
      </div>
      <div style="height:8px"></div>
      <div style="opacity:.75;font-size:12px">${escapeHtml(pi.note || '')}</div>
    </div>
  `;
  const rounds = pi.rounds.map(r => {
    const segs = (r.segments || []).map(s => {
      const detail = s.hex
        ? `<div class="bubble" style="margin-top:6px;font-family:ui-monospace,Menlo,monospace;font-size:11px;word-break:break-all"><span style="opacity:.7">hex:</span> ${escapeHtml(s.hex)}</div>`
        : (s.sha256
            ? `<div class="bubble" style="margin-top:6px;font-family:ui-monospace,Menlo,monospace;font-size:11px;word-break:break-all"><span style="opacity:.7">sha256:</span> ${escapeHtml(s.sha256)}</div>`
            : '');
      return `<div style="padding:8px 10px;border-top:1px solid rgba(255,255,255,.06)">
        <div style="display:flex;gap:10px;align-items:baseline;flex-wrap:wrap">
          <b style="font-family:ui-monospace,Menlo,monospace;color:#9ec5ff">${escapeHtml(s.name)}</b>
          <span style="opacity:.7;font-size:12px">${s.bytes} bytes</span>
        </div>
        <div style="opacity:.88;font-size:12px;margin-top:4px">${escapeHtml(s.note || '')}</div>
        ${detail}
      </div>`;
    }).join('');
    return `
      <div class="bubble" style="padding:0;overflow:hidden">
        <div style="padding:12px 14px;background:rgba(255,255,255,.04);border-bottom:1px solid rgba(255,255,255,.06)">
          <div style="display:flex;gap:10px;align-items:baseline;flex-wrap:wrap">
            <b style="font-family:ui-monospace,Menlo,monospace;color:#ffd49a">phase=${escapeHtml(r.phase)}</b>
            <span style="opacity:.7;font-size:12px">${escapeHtml(r.dir || '')}</span>
            <span style="opacity:.7;font-size:12px;margin-left:auto">${r.bytes} bytes total</span>
          </div>
          <div style="opacity:.92;margin-top:6px;line-height:1.5;font-size:13px">${escapeHtml(r.explainer || '')}</div>
        </div>
        ${segs}
      </div>
    `;
  }).join('<div style="height:10px"></div>');
  setPanel('#panel-psi', intro + '<div style="height:10px"></div>' + rounds);
}

function renderRefusalsReference(trace){
  const refusal = trace ? _refusalFromTrace(trace) : null;
  const activeCode = refusal?.error_code || null;
  const rows = Object.entries(REFUSAL_HINTS).map(([code, { hint, audit }]) => {
    const isActive = code === activeCode;
    return `<tr${isActive ? ' style="background:rgba(255,124,124,.08)"' : ''}>
      <td style="vertical-align:top;padding:8px 10px;font-family:ui-monospace,Menlo,monospace;color:${isActive ? '#FF7C7C' : '#FFD9A6'};white-space:nowrap">${escapeHtml(code)}${isActive ? ' &larr;' : ''}</td>
      <td style="vertical-align:top;padding:8px 10px;opacity:.92">${escapeHtml(hint)}</td>
      <td style="vertical-align:top;padding:8px 10px;font-family:ui-monospace,Menlo,monospace;opacity:.85;white-space:nowrap">${escapeHtml(audit)}</td>
    </tr>`;
  }).join('');
  const intro = activeCode
    ? `This run was refused with <b style="font-family:ui-monospace,Menlo,monospace;color:#FF7C7C">${escapeHtml(activeCode)}</b>. The full table is below for context.`
    : `Every refusal the receiver can emit. Each row links the error code to the receiver-side check that produced it &mdash; useful while reading <code>_core.py</code> or designing tests.`;
  setPanel('#panel-refusals', `
    <div class="bubble">
      <div style="font-weight:700;margin-bottom:8px">Receiver refusal codes</div>
      <div style="opacity:.9;margin-bottom:12px">${intro}</div>
      <table style="border-collapse:collapse;width:100%;font-size:13px">
        <thead>
          <tr style="text-align:left;border-bottom:1px solid rgba(255,255,255,.12)">
            <th style="padding:6px 10px;font-weight:700">error_code</th>
            <th style="padding:6px 10px;font-weight:700">What the receiver checked</th>
            <th style="padding:6px 10px;font-weight:700">Audit event</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  `);
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
  renderPsi(trace);
  renderRefusalsReference(trace);
  renderLogs(trace);

  // A run worth sharing is one that produced envelopes (the protocol actually ran).
  const shareable = !!(trace?.envelopes?.length);
  const btn = $('#btn-share-run');
  if (btn) btn.disabled = !shareable;

  const ok = trace.result?.ok;
  if (ok) setChat(`Result: OK`);
  else setChat(`Result: ERROR — ${pretty(trace.result?.error || trace.result)}`);
}

async function shareCurrentRun(){
  const trace = window.__lastTrace;
  if (!trace){
    setChat('No run to share yet — finish the walkthrough first.');
    return;
  }
  const btn = $('#btn-share-run');
  if (btn) { btn.disabled = true; btn.textContent = 'Sharing…'; }
  try {
    const res = await fetch('/api/runs', {method:'POST', headers:{'content-type':'application/json'}, body: JSON.stringify({trace})});
    const out = await res.json();
    if (!out.ok || !out.run_id) throw new Error(out.error || 'save failed');
    const url = `${location.origin}${location.pathname}?run=${out.run_id}`;
    await copyText(url);
    setChat(`Sharable link copied: ${url} (valid for ~24h, demo storage only)`);
  } catch(e) {
    setChat(`Share failed: ${e.message || e}`);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'Share this run'; }
  }
}

async function maybeLoadSharedRun(){
  const params = new URLSearchParams(location.search);
  const runId = params.get('run');
  if (!runId) return false;
  try {
    const res = await fetch(`/api/runs/${encodeURIComponent(runId)}`);
    if (!res.ok){
      setChat(`Shared run ${runId} not found or expired.`);
      return false;
    }
    const out = await res.json();
    if (!out.ok || !out.trace){
      setChat(`Shared run ${runId} not loadable.`);
      return false;
    }
    showView('playground');
    renderAll(out.trace);
    setChat(`Viewing shared run ${runId}. Start a new walkthrough to make your own.`);
    return true;
  } catch(e) {
    setChat(`Load shared run failed: ${e.message || e}`);
    return false;
  }
}

function attackState(){
  return {
    tamper_session_id: $('#atk-session-id')?.checked || false,
    tamper_participants: $('#atk-participants')?.checked || false,
    tamper_msg1_payload: $('#atk-msg1')?.checked || false,
    replay: $('#atk-replay')?.checked || false,
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
  { title:'Send first envelope', text:'Initiator sends the opening ProtocolEnvelope (phase init) over A2A JSON-RPC (inspect raw HTTP).', tab:'a2ahttp' },
  { title:'Receiver checks', text:'Receiver validates session binding, participants, signature, payload_hash, replay.', tab:'audit' },
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
$('#btn-share-run')?.addEventListener('click', shareCurrentRun);

// Delegated copy-button handler: any element with [data-copy-payload]
// copies its payload to clipboard. See copyButton() for the producer side.
document.addEventListener('click', (e) => {
  const btn = e.target?.closest?.('[data-copy-payload]');
  if (btn) copyText(btn.getAttribute('data-copy-payload'));
});

$('#btn-attacks-reset')?.addEventListener('click', () => {
  ['#atk-session-id', '#atk-participants', '#atk-msg1', '#atk-replay'].forEach(id => {
    const el = $(id);
    if (el) el.checked = false;
  });
});
$('#btn-walkthrough-next')?.addEventListener('click', async () => {
  walkthrough.step = Math.min(STEPS.length-1, walkthrough.step+1);

  // Step 2: compatibility preflight (no protocol run).
  if (walkthrough.step === 1){
    await walkthroughPrefetchCompat();
  }

  // Step 3: send msg1 (no finalize).
  if (walkthrough.step === 2){
    setChat('Walkthrough: sending first envelope (initiator → receiver)…');
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
renderRefusalsReference(null);
renderPsi(null);

// If launched via ?run=ID, fetch and render the shared run.
maybeLoadSharedRun();

['#psi-success', '#psi-fail'].forEach(id => $(id)?.addEventListener('change', () => renderPsiDataPanel()));

