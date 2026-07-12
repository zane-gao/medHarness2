from __future__ import annotations


def dynamic_control_panel_html() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>medHarness2 Control Panel</title>
  <style>
    :root { color-scheme: light; --line:#d7dde5; --ink:#17212b; --muted:#5e6b78; --panel:#f6f8fa; --ok:#176b3a; --warn:#8a5a00; --bad:#a12622; }
    * { box-sizing:border-box; }
    body { margin:0; color:var(--ink); background:#fff; font:14px/1.45 system-ui,sans-serif; }
    header { display:flex; align-items:center; justify-content:space-between; min-height:56px; padding:0 20px; border-bottom:1px solid var(--line); }
    h1 { margin:0; font-size:19px; letter-spacing:0; }
    h2 { margin:0 0 10px; font-size:15px; letter-spacing:0; }
    button,input { min-height:34px; border:1px solid #aeb8c4; border-radius:4px; background:#fff; padding:6px 10px; }
    button { cursor:pointer; font-weight:600; }
    main { padding:18px 20px 40px; }
    .metrics { display:flex; gap:24px; padding:12px 0 18px; border-bottom:1px solid var(--line); margin-bottom:18px; }
    .metric b { display:block; font-size:21px; }
    .metric span { color:var(--muted); }
    .layout { display:grid; grid-template-columns:minmax(0,2fr) minmax(300px,1fr); gap:18px; }
    section { margin-bottom:22px; }
    .table-wrap { overflow:auto; border:1px solid var(--line); border-radius:6px; }
    table { border-collapse:collapse; width:100%; min-width:720px; }
    th,td { padding:8px 10px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; }
    th { background:var(--panel); font-size:12px; color:#3d4a57; }
    tr:last-child td { border-bottom:0; }
    tr[data-run] { cursor:pointer; }
    tr[data-run]:hover { background:#f7fafc; }
    pre { margin:0; min-height:240px; max-height:520px; overflow:auto; padding:12px; border:1px solid var(--line); border-radius:6px; background:#101820; color:#e8eef4; font-size:12px; }
    .toolbar { display:flex; gap:8px; align-items:center; }
    .status-validated,.status-succeeded { color:var(--ok); font-weight:700; }
    .status-pilot,.status-running,.status-queued { color:var(--warn); font-weight:700; }
    .status-not_ready,.status-failed,.status-cancelled { color:var(--bad); font-weight:700; }
    code { white-space:pre-wrap; }
    @media (max-width:900px) { .layout { grid-template-columns:1fr; } .metrics { flex-wrap:wrap; } header { align-items:flex-start; padding:12px 16px; } }
  </style>
</head>
<body>
<header><h1>medHarness2 Control Panel</h1><div class="toolbar"><input id="runDir" value="outputs/sample_data_2026-06-05_final_local_routed_52_20260606_reeval_tool2_v1" aria-label="Run directory"><button id="refresh">Refresh</button></div></header>
<main>
  <div class="metrics"><div class="metric"><b id="runCount">0</b><span>Runs</span></div><div class="metric"><b id="activeCount">0</b><span>Active</span></div><div class="metric"><b id="toolCount">0</b><span>Tools</span></div><div class="metric"><b id="validatedCount">0</b><span>Validated studies</span></div></div>
  <div class="layout"><div>
    <section><h2>Runs</h2><div class="table-wrap"><table><thead><tr><th>Run</th><th>Type</th><th>Status</th><th>Updated</th><th>Retries</th></tr></thead><tbody id="runs"></tbody></table></div></section>
    <section><h2>Experiment Gates</h2><div class="table-wrap"><table><thead><tr><th>Experiment</th><th>Status</th><th>Gates</th><th>Pending</th></tr></thead><tbody id="experiments"></tbody></table></div></section>
    <section><h2>Model/API Routing</h2><div class="table-wrap"><table><thead><tr><th>Role</th><th>Provider</th><th>Model</th><th>Endpoint</th></tr></thead><tbody id="modelRoles"></tbody></table></div></section>
    <section><h2>Tool Implementation</h2><div class="table-wrap"><table><thead><tr><th>Tool</th><th>Implementation</th><th>Inputs</th><th>Outputs</th></tr></thead><tbody id="tools"></tbody></table></div></section>
  </div><aside><section><h2>Run Details</h2><pre id="details">{}</pre></section></aside></div>
</main>
<script>
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function loadRuns(){const data=await fetch('/runs').then(r=>r.json());runCount.textContent=data.runs.length;activeCount.textContent=data.runs.filter(x=>['queued','running'].includes(x.status)).length;runs.innerHTML=data.runs.map(x=>`<tr data-run="${esc(x.run_id)}"><td><code>${esc(x.run_id)}</code></td><td>${esc(x.run_type)}</td><td class="status-${esc(x.status)}">${esc(x.status)}</td><td>${esc(x.updated_at_utc)}</td><td>${x.retry_count}</td></tr>`).join('');document.querySelectorAll('[data-run]').forEach(row=>row.onclick=async()=>{details.textContent=JSON.stringify(await fetch('/runs/'+row.dataset.run).then(r=>r.json()),null,2)});}
async function loadTools(){const data=await fetch('/catalog/tools?config_path=config/dmx_strong.yaml').then(r=>r.json());toolCount.textContent=data.tools.length;tools.innerHTML=data.tools.map(x=>`<tr><td><code>${esc(x.id)}</code></td><td>${esc(x.implementation_type)}<br>${esc(x.implementation)}</td><td>${esc(x.inputs.join(', '))}</td><td>${esc(x.outputs.join(', '))}</td></tr>`).join('');const roles=data.providers.model_roles||{};modelRoles.innerHTML=Object.entries(roles).map(([name,x])=>`<tr><td><code>${esc(name)}</code></td><td>${esc(x.provider)}</td><td>${esc(x.model)}</td><td>${esc(x.endpoint_host||'local')}</td></tr>`).join('');}
async function loadExperiments(){const dir=encodeURIComponent(runDir.value);const data=await fetch('/experiments?run_dir='+dir).then(r=>r.json());validatedCount.textContent=data.experiments.filter(x=>x.status==='validated').length;experiments.innerHTML=data.experiments.map(x=>{const pending=(x.validation_gates||[]).filter(g=>!g.passed).map(g=>g.id).join(', ');return `<tr><td>${esc(x.title)}</td><td class="status-${esc(x.status)}">${esc(x.status)}</td><td>${x.gate_summary.passed}/${x.gate_summary.total}</td><td><code>${esc(pending)}</code></td></tr>`}).join('');}
async function refresh(){await Promise.all([loadRuns(),loadTools(),loadExperiments()]);}
document.getElementById('refresh').onclick=refresh;refresh();setInterval(loadRuns,5000);
</script>
</body></html>"""
