/* PROSPECTOR — Frontend JS */
'use strict';

// ─── State ────────────────────────────────────────────────────────────────
const S = {
  module: 'dashboard',
  leads: [], artisans: [], contracts: [], commissions: [], transmissions: [],
  chatHistory: [],
  alertCount: 0,
  // Filters
  leadFilters: { statut: '', score_min: '' },
  artisanFilters: { contrat_signe: '' },
};

// ─── API helper ───────────────────────────────────────────────────────────
async function api(method, path, body, isForm = false) {
  const opts = { method, headers: {} };
  if (body && !isForm) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  } else if (body && isForm) {
    opts.body = body;
  }
  try {
    const res = await fetch('/api' + path, opts);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || JSON.stringify(data));
    return data;
  } catch (e) {
    throw e;
  }
}

// ─── Toast ────────────────────────────────────────────────────────────────
function toast(msg, type = 'ok', duration = 4000) {
  const c = document.getElementById('toasts');
  const t = document.createElement('div');
  t.className = 'toast' + (type !== 'ok' ? ' ' + type : '');
  t.textContent = msg;
  c.appendChild(t);
  setTimeout(() => t.remove(), duration);
}

// ─── Navigation ──────────────────────────────────────────────────────────
function navigate(mod) {
  S.module = mod;
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  const panel = document.getElementById('panel-' + mod);
  const nav = document.querySelector('[data-mod="' + mod + '"]');
  if (panel) panel.classList.add('active');
  if (nav) nav.classList.add('active');
  loadModule(mod);
}

function loadModule(mod) {
  switch (mod) {
    case 'dashboard': loadDashboard(); break;
    case 'leads': loadLeads(); break;
    case 'artisans': loadArtisans(); break;
    case 'contracts': loadContracts(); break;
    case 'commissions': loadCommissions(); break;
    case 'chat': break;
  }
}

// ─── Drawer ───────────────────────────────────────────────────────────────
function openDrawer(title, bodyHTML, onSave, saveLabel = 'Enregistrer') {
  document.getElementById('drawer-title').textContent = title;
  document.getElementById('drawer-body').innerHTML = bodyHTML;
  document.getElementById('drawer-save').textContent = saveLabel;
  document.getElementById('drawer-save').onclick = onSave;
  document.getElementById('drawer-overlay').classList.add('open');
  document.getElementById('drawer').classList.add('open');
}

function closeDrawer() {
  document.getElementById('drawer-overlay').classList.remove('open');
  document.getElementById('drawer').classList.remove('open');
}

// ─── Modal ─────────────────────────────────────────────────────────────────
function openModal(title, bodyHTML, actions = '') {
  document.getElementById('modal-title').textContent = title;
  document.getElementById('modal-body').innerHTML = bodyHTML;
  document.getElementById('modal-actions').innerHTML = actions;
  document.getElementById('modal-overlay').classList.add('open');
}

function closeModal() {
  document.getElementById('modal-overlay').classList.remove('open');
}

// ─── Helpers ──────────────────────────────────────────────────────────────
function badge(val, map) {
  const cls = map[val] || 'badge-nouveau';
  return `<span class="badge ${cls}">${val || '—'}</span>`;
}

const STATUT_LEAD = {
  nouveau: 'badge-nouveau', qualifie: 'badge-qualifie',
  transmis: 'badge-transmis', devis_envoye: 'badge-devis_envoye',
  signe: 'badge-signe', commission_payee: 'badge-commission_payee', perdu: 'badge-perdu'
};

const STATUT_COMM = {
  en_attente: 'badge-en_attente', payee: 'badge-signe',
  en_retard: 'badge-en_retard', contentieux: 'badge-contentieux'
};

function scorePill(s) {
  const cls = s >= 70 ? 'score-high' : s >= 40 ? 'score-mid' : 'score-low';
  return `<span class="score ${cls}">${s}</span>`;
}

function urgenceDots(u) {
  let html = '<span class="urgence-dots">';
  for (let i = 1; i <= 5; i++) html += `<span class="urgence-dot ${i <= u ? 'on' : ''}"></span>`;
  return html + '</span>';
}

function fmt(n) {
  if (!n) return '—';
  return new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 }).format(n);
}

function fmtDate(s) {
  if (!s) return '—';
  try { return new Date(s).toLocaleDateString('fr-FR'); } catch { return s; }
}

function trunc(s, n = 30) {
  if (!s) return '—';
  return s.length > n ? s.slice(0, n) + '…' : s;
}

function el(id) { return document.getElementById(id); }

// ─── MODULE: DASHBOARD ────────────────────────────────────────────────────
async function loadDashboard() {
  try {
    const [stats, pipeline, alerts] = await Promise.all([
      api('GET', '/dashboard/stats'),
      api('GET', '/dashboard/pipeline'),
      api('GET', '/crm/alerts'),
    ]);
    renderDashboardStats(stats);
    renderPipeline(pipeline.pipeline);
    renderAlerts(alerts.alerts);

    // Update alert badge
    const count = alerts.alerts.length;
    const badge = el('alert-badge');
    if (badge) { badge.textContent = count; badge.style.display = count ? '' : 'none'; }
  } catch (e) {
    toast('Erreur chargement dashboard : ' + e.message, 'err');
  }
}

function renderDashboardStats(s) {
  el('stat-leads-actifs').innerHTML = `<div class="lbl">Leads actifs</div><div class="val">${s.leads.actifs}</div><div class="sub">${s.leads.nouveaux} nouveaux</div>`;
  el('stat-artisans').innerHTML = `<div class="lbl">Artisans</div><div class="val">${s.artisans.total}</div><div class="sub">${s.artisans.avec_contrat} avec contrat signé</div>`;
  el('stat-commissions').innerHTML = `<div class="lbl">En attente</div><div class="val">${fmt(s.commissions.en_attente_montant)}</div><div class="sub">${s.commissions.en_retard_count > 0 ? `⚠️ ${s.commissions.en_retard_count} en retard` : 'Aucun retard'}</div>`;
  el('stat-ca').innerHTML = `<div class="lbl">CA ce mois</div><div class="val">${fmt(s.commissions.ca_mois)}</div><div class="sub">Total encaissé : ${fmt(s.commissions.ca_total)}</div>`;
}

function renderPipeline(cols) {
  const pipelineEl = el('pipeline');
  const colors = {
    nouveau: '#64748b', qualifie: '#3b82f6', transmis: '#f97316',
    devis_envoye: '#8b5cf6', signe: '#10b981', commission_payee: '#059669', perdu: '#ef4444'
  };
  pipelineEl.innerHTML = cols.map(col => `
    <div class="pipeline-col">
      <div class="pipeline-col-hdr" style="border-top: 3px solid ${colors[col.statut] || '#ccc'}; border-radius: 10px 10px 0 0">
        <span class="pipeline-col-title" style="color: ${colors[col.statut] || '#64748b'}">${col.label}</span>
        <span class="pipeline-col-count">${col.count}</span>
      </div>
      <div class="pipeline-col-body">
        ${col.leads.slice(0, 5).map(l => `
          <div class="pipeline-card" onclick="navigate('leads')">
            <div class="pc-travaux">${trunc(l.type_travaux, 25) || 'Travaux'}</div>
            <div class="pc-meta">${trunc(l.localisation, 20) || '—'} · ${scorePill(l.score)}</div>
          </div>
        `).join('')}
        ${col.leads.length > 5 ? `<div style="text-align:center;font-size:11px;color:var(--text-muted);padding:4px">+${col.leads.length - 5} autres</div>` : ''}
      </div>
      ${col.total_montant > 0 ? `<div class="pipeline-col-total">${fmt(col.total_montant)}</div>` : ''}
    </div>
  `).join('');
}

function renderAlerts(alerts) {
  const c = el('alerts-container');
  if (!alerts.length) {
    c.innerHTML = '<div class="alert alert-s"><span class="alert-icon">✅</span><span>Aucune alerte — tout est à jour !</span></div>';
    return;
  }
  const icons = { lead_sans_nouvelle: '⏰', commission_en_retard: '💸', lead_non_traite: '📋' };
  const cls = { warning: 'alert-w', danger: 'alert-d', info: 'alert-i' };
  c.innerHTML = alerts.slice(0, 8).map(a => `
    <div class="alert ${cls[a.severity] || 'alert-i'}">
      <span class="alert-icon">${icons[a.type] || '⚠️'}</span>
      <div class="alert-msg">
        <div>${a.message}</div>
        ${a.lead_id ? `<div class="alert-actions"><button class="btn btn-sm btn-outline" onclick="navigate('leads')">Voir lead</button></div>` : ''}
        ${a.commission_id ? `<div class="alert-actions">
          <button class="btn btn-sm btn-outline" onclick="navigate('commissions')">Voir commission</button>
          <button class="btn btn-sm btn-warning" onclick="generateRelanceFromAlert(${a.commission_id})">Générer relance</button>
        </div>` : ''}
      </div>
    </div>
  `).join('');
}

// ─── MODULE: LEADS ────────────────────────────────────────────────────────
async function loadLeads() {
  el('leads-table-body').innerHTML = '<tr><td colspan="9" class="loading"><div class="spin" style="border:2px solid #ccc;border-top-color:var(--accent);border-radius:50%;width:18px;height:18px;display:inline-block;"></div> Chargement…</td></tr>';
  try {
    const params = new URLSearchParams();
    if (S.leadFilters.statut) params.set('statut', S.leadFilters.statut);
    if (S.leadFilters.score_min) params.set('score_min', S.leadFilters.score_min);
    const data = await api('GET', '/leads/?' + params);
    S.leads = data.leads;
    renderLeadsTable(data.leads, data.total);
  } catch (e) {
    toast('Erreur leads : ' + e.message, 'err');
  }
}

function renderLeadsTable(leads, total) {
  el('leads-count').textContent = `${total || leads.length} leads`;
  const body = el('leads-table-body');
  if (!leads.length) {
    body.innerHTML = '<tr><td colspan="9"><div class="empty"><div class="empty-icon">🎯</div><p>Aucun lead — importez depuis open data ou ajoutez manuellement</p></div></td></tr>';
    return;
  }
  body.innerHTML = leads.map(l => `
    <tr>
      <td>${scorePill(l.score)}</td>
      <td><strong>${trunc(l.type_travaux, 28) || '—'}</strong></td>
      <td>${trunc(l.localisation, 20) || '—'}</td>
      <td><div>${l.contact_nom || '—'}</div><div style="font-size:11px;color:var(--text-muted)">${l.contact_tel || ''}</div></td>
      <td>${urgenceDots(l.urgence || 3)}</td>
      <td>${badge(l.statut, STATUT_LEAD)}</td>
      <td>${l.artisan_nom ? `<span class="tag">${trunc(l.artisan_nom, 18)}</span>` : '—'}</td>
      <td>${l.commission_attendue ? fmt(l.commission_attendue) : '—'}</td>
      <td class="td-actions">
        <button class="btn btn-sm btn-outline" onclick="showLeadDetail(${l.id})" title="Voir">👁</button>
        <button class="btn btn-sm btn-outline" onclick="showLeadForm(${l.id})" title="Modifier">✏️</button>
        <button class="btn btn-sm btn-primary" onclick="showTransmitLead(${l.id})" title="Transmettre">📤</button>
        <button class="btn btn-sm btn-ghost" onclick="deleteLead(${l.id})" title="Supprimer">🗑</button>
      </td>
    </tr>
  `).join('');
}

function showLeadForm(leadId = null) {
  const lead = leadId ? S.leads.find(l => l.id === leadId) : null;
  const title = lead ? 'Modifier le lead' : 'Nouveau lead';
  const statusOptions = ['nouveau', 'qualifie', 'transmis', 'devis_envoye', 'signe', 'commission_payee', 'perdu'];

  const html = `
    <form id="lead-form">
      <div class="form-row">
        <div class="form-group">
          <label>Type de travaux *</label>
          <input name="type_travaux" value="${lead?.type_travaux || ''}" placeholder="Ex: Isolation, PAC, Extension…" required>
        </div>
        <div class="form-group">
          <label>Localisation</label>
          <input name="localisation" value="${lead?.localisation || 'Rennes'}" placeholder="Ville ou adresse">
        </div>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label>Budget estimé (€)</label>
          <input type="number" name="budget_estime" value="${lead?.budget_estime || ''}" placeholder="0" min="0">
        </div>
        <div class="form-group">
          <label>Montant chantier (€)</label>
          <input type="number" name="montant_chantier_estime" value="${lead?.montant_chantier_estime || ''}" placeholder="0" min="0">
        </div>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label>Contact — Nom</label>
          <input name="contact_nom" value="${lead?.contact_nom || ''}" placeholder="Prénom Nom">
        </div>
        <div class="form-group">
          <label>Téléphone</label>
          <input name="contact_tel" value="${lead?.contact_tel || ''}" placeholder="06 XX XX XX XX">
        </div>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label>Email</label>
          <input type="email" name="contact_email" value="${lead?.contact_email || ''}" placeholder="email@exemple.fr">
        </div>
        <div class="form-group">
          <label>Urgence (1-5)</label>
          <select name="urgence">
            ${[1,2,3,4,5].map(i => `<option value="${i}" ${(lead?.urgence || 3) == i ? 'selected' : ''}>${i} — ${['Très faible','Faible','Normale','Haute','Urgente'][i-1]}</option>`).join('')}
          </select>
        </div>
      </div>
      ${lead ? `<div class="form-group">
        <label>Statut</label>
        <select name="statut">
          ${statusOptions.map(s => `<option value="${s}" ${lead.statut === s ? 'selected' : ''}>${s.replace('_',' ')}</option>`).join('')}
        </select>
      </div>` : ''}
      <div class="form-group">
        <label>Notes</label>
        <textarea name="notes" rows="3" placeholder="Informations complémentaires…">${lead?.notes || ''}</textarea>
      </div>
    </form>
  `;

  openDrawer(title, html, async () => {
    const form = el('lead-form');
    const fd = new FormData(form);
    const data = Object.fromEntries(fd.entries());
    // Convertir les nombres
    ['budget_estime', 'montant_chantier_estime', 'urgence'].forEach(k => {
      if (data[k]) data[k] = parseFloat(data[k]);
    });
    try {
      if (lead) {
        await api('PUT', `/leads/${lead.id}`, data);
        toast('Lead mis à jour ✓');
      } else {
        await api('POST', '/leads/', data);
        toast('Lead créé ✓');
      }
      closeDrawer();
      loadLeads();
    } catch (e) {
      toast('Erreur : ' + e.message, 'err');
    }
  });
}

function showLeadDetail(leadId) {
  const lead = S.leads.find(l => l.id === leadId);
  if (!lead) return;
  openModal(`Lead #${leadId} — ${lead.type_travaux || 'Travaux'}`,
    `<div class="two-col">
      <div>
        <p><strong>Type :</strong> ${lead.type_travaux || '—'}</p>
        <p><strong>Localisation :</strong> ${lead.localisation || '—'}</p>
        <p><strong>Budget estimé :</strong> ${fmt(lead.budget_estime)}</p>
        <p><strong>Montant chantier :</strong> ${fmt(lead.montant_chantier_estime)}</p>
        <p><strong>Commission attendue :</strong> ${fmt(lead.commission_attendue)}</p>
        <p><strong>Urgence :</strong> ${urgenceDots(lead.urgence)}</p>
        <p><strong>Score :</strong> ${scorePill(lead.score)}</p>
        <p><strong>Statut :</strong> ${badge(lead.statut, STATUT_LEAD)}</p>
      </div>
      <div>
        <p><strong>Contact :</strong> ${lead.contact_nom || '—'}</p>
        <p><strong>Tél :</strong> ${lead.contact_tel || '—'}</p>
        <p><strong>Email :</strong> ${lead.contact_email || '—'}</p>
        <p><strong>Source :</strong> <span class="tag">${lead.source}</span></p>
        <p><strong>Artisan :</strong> ${lead.artisan_nom || '—'}</p>
        <p><strong>Créé le :</strong> ${fmtDate(lead.created_at)}</p>
        <p><strong>Modifié :</strong> ${fmtDate(lead.updated_at)}</p>
      </div>
    </div>
    ${lead.notes ? `<hr><p><strong>Notes :</strong></p><p style="white-space:pre-wrap;font-size:13px">${lead.notes}</p>` : ''}`,
    `<button class="btn btn-outline" onclick="closeModal()">Fermer</button>
     <button class="btn btn-primary" onclick="closeModal();showLeadForm(${leadId})">Modifier</button>`
  );
}

async function deleteLead(id) {
  if (!confirm('Supprimer ce lead ?')) return;
  try {
    await api('DELETE', `/leads/${id}`);
    toast('Lead supprimé');
    loadLeads();
  } catch (e) {
    toast('Erreur : ' + e.message, 'err');
  }
}

async function showTransmitLead(leadId) {
  const lead = S.leads.find(l => l.id === leadId);
  if (!lead) return;
  // Charger les artisans si la liste est vide (accès direct depuis Leads sans passer par Artisans)
  if (!S.artisans.length) await loadArtisans();
  const artisansOpts = S.artisans.map(a =>
    `<option value="${a.id}">${a.nom} — ${a.metier || ''} — ${a.ville || ''}</option>`
  ).join('');

  const html = `
    <div class="disclaimer">⚠️ L'email de transmission est un DRAFT — vous l'envoyez vous-même depuis votre client mail. Il constitue votre preuve de transmission.</div>
    <div class="form-group">
      <label>Lead à transmettre</label>
      <div style="background:var(--bg);border-radius:7px;padding:10px;font-size:13px">
        <strong>${lead.type_travaux || 'Travaux'}</strong> — ${lead.localisation || '—'}<br>
        Contact : ${lead.contact_nom || '—'} — ${lead.contact_tel || 'Tél non renseigné'}
      </div>
    </div>
    <div class="form-group">
      <label>Artisan partenaire *</label>
      <select id="transmit-artisan">${artisansOpts || '<option>Aucun artisan disponible</option>'}</select>
    </div>
    <div class="form-group">
      <label>Notes (optionnel)</label>
      <textarea id="transmit-notes" rows="2" placeholder="Notes internes…"></textarea>
    </div>
    <div id="transmit-draft" style="display:none">
      <div class="section-title">📧 Draft email généré</div>
      <div class="draft-box" id="draft-content"></div>
    </div>
  `;

  openDrawer('Transmettre le lead', html, async () => {
    const artisan_id = parseInt(el('transmit-artisan').value);
    const notes = el('transmit-notes').value;
    if (!artisan_id) { toast('Sélectionnez un artisan', 'warn'); return; }
    try {
      const result = await api('POST', '/crm/transmissions', { lead_id: leadId, artisan_id, notes });
      el('draft-content').textContent = result.email_draft;
      el('transmit-draft').style.display = 'block';
      toast('Transmission créée — Draft email prêt ✓');
      // Copier le draft dans le presse-papier
      if (navigator.clipboard) {
        await navigator.clipboard.writeText(result.email_draft);
        toast('Draft copié dans le presse-papier', 'info');
      }
      loadLeads();
    } catch (e) {
      toast('Erreur : ' + e.message, 'err');
    }
  }, 'Transmettre & Générer draft');
}

// Extract lead from text via IA
async function showExtractModal() {
  openModal('📋 Import IA — Coller un texte',
    `<p style="font-size:13px;color:var(--text-muted);margin-bottom:10px">Collez ici un post Facebook, une annonce, une conversation… L'IA extrait automatiquement les informations du lead.</p>
     <textarea id="extract-text" rows="8" placeholder="Ex: Bonjour, je cherche un artisan pour isoler mes combles perdus d'environ 120m2. Budget autour de 5000€. Disponible à partir de septembre. Je suis sur Rennes (35). Mon tel: 06 12 34 56 78 - Marie Dupont"></textarea>`,
    `<button class="btn btn-outline" onclick="closeModal()">Annuler</button>
     <button class="btn btn-primary" onclick="extractLead()">🤖 Extraire avec l'IA</button>`
  );
}

async function extractLead() {
  const text = el('extract-text').value.trim();
  if (!text) { toast('Collez du texte d\'abord', 'warn'); return; }

  document.querySelector('.modal-ftr .btn-primary').innerHTML = '<span class="spin"></span> Extraction…';
  document.querySelector('.modal-ftr .btn-primary').disabled = true;

  try {
    const result = await api('POST', '/leads/extract', { text });
    if (!result.success) {
      toast('Erreur IA : ' + (result.error || 'Réponse invalide'), 'err');
      return;
    }
    closeModal();
    // Pré-remplir le formulaire
    const d = result.data;
    // Patcher S.leads temporairement pour showLeadForm
    const fakeLead = { ...d, id: null };
    openDrawer('Nouveau lead (pré-rempli par IA)', buildLeadFormHTML(fakeLead), async () => {
      const form = el('lead-form');
      const fd = new FormData(form);
      const data = Object.fromEntries(fd.entries());
      ['budget_estime', 'montant_chantier_estime', 'urgence'].forEach(k => {
        if (data[k]) data[k] = parseFloat(data[k]);
      });
      data.raw_text = text;
      try {
        await api('POST', '/leads/', data);
        toast('Lead créé depuis extraction IA ✓');
        closeDrawer();
        loadLeads();
      } catch (e) {
        toast('Erreur : ' + e.message, 'err');
      }
    });
  } catch (e) {
    toast('Erreur IA : ' + e.message, 'err');
  }
}

function buildLeadFormHTML(lead) {
  return `
    <form id="lead-form">
      <div class="form-row">
        <div class="form-group">
          <label>Type de travaux *</label>
          <input name="type_travaux" value="${lead?.type_travaux || ''}" placeholder="Ex: Isolation, PAC…" required>
        </div>
        <div class="form-group">
          <label>Localisation</label>
          <input name="localisation" value="${lead?.localisation || 'Rennes'}" placeholder="Ville ou adresse">
        </div>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label>Budget estimé (€)</label>
          <input type="number" name="budget_estime" value="${lead?.budget_estime || ''}" min="0">
        </div>
        <div class="form-group">
          <label>Montant chantier (€)</label>
          <input type="number" name="montant_chantier_estime" value="${lead?.montant_chantier_estime || ''}" min="0">
        </div>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label>Contact — Nom</label>
          <input name="contact_nom" value="${lead?.contact_nom || ''}" placeholder="Prénom Nom">
        </div>
        <div class="form-group">
          <label>Téléphone</label>
          <input name="contact_tel" value="${lead?.contact_tel || ''}" placeholder="06 XX XX XX XX">
        </div>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label>Email</label>
          <input type="email" name="contact_email" value="${lead?.contact_email || ''}" placeholder="email@exemple.fr">
        </div>
        <div class="form-group">
          <label>Urgence (1-5)</label>
          <select name="urgence">
            ${[1,2,3,4,5].map(i => `<option value="${i}" ${(lead?.urgence || 3) == i ? 'selected' : ''}>${i} — ${['Très faible','Faible','Normale','Haute','Urgente'][i-1]}</option>`).join('')}
          </select>
        </div>
      </div>
      <div class="form-group">
        <label>Notes</label>
        <textarea name="notes" rows="3" placeholder="Informations complémentaires…">${lead?.notes || ''}</textarea>
      </div>
    </form>
  `;
}

async function showOpenDataModal() {
  openModal('🏗️ Veille Open Data — Permis de construire',
    `<p style="font-size:13px;color:var(--text-muted);margin-bottom:12px">Récupère les permis de construire récents depuis data.gouv.fr / Sitadel (DGALN). Source légale, open data public.</p>
     <div class="form-row">
       <div class="form-group"><label>Commune</label><input id="od-commune" value="Rennes"></div>
       <div class="form-group"><label>Département</label><input id="od-dept" value="35" maxlength="3"></div>
     </div>
     <div class="form-group"><label>Nombre max de résultats</label><input type="number" id="od-limit" value="20" min="1" max="100"></div>
     <div id="od-results"></div>`,
    `<button class="btn btn-outline" onclick="closeModal()">Fermer</button>
     <button class="btn btn-secondary" onclick="fetchOD()">🔍 Récupérer</button>
     <button class="btn btn-primary" id="od-import-btn" style="display:none" onclick="importOD()">⬇️ Tout importer</button>`
  );
}

async function fetchOD() {
  const commune = el('od-commune').value;
  const dept = el('od-dept').value;
  const limit = parseInt(el('od-limit').value) || 20;
  el('od-results').innerHTML = '<div class="loading"><span class="spin" style="border:2px solid #ccc;border-top-color:var(--accent);border-radius:50%;width:16px;height:16px;display:inline-block;margin-right:6px"></span> Interrogation data.gouv.fr…</div>';
  try {
    const result = await api('POST', '/leads/open-data/fetch', { commune, code_dept: dept, limit });
    const leads = result.leads || [];
    // La modal peut avoir été fermée pendant l'appel réseau
    if (!el('od-import-btn')) return;
    el('od-import-btn').style.display = leads.length ? '' : 'none';
    el('od-results').innerHTML = `
      ${result.errors?.length ? `<div class="alert alert-i" style="margin-bottom:10px"><span>ℹ️</span><span>${result.errors.join('<br>')}</span></div>` : ''}
      <div class="section-title">${leads.length} résultat(s)</div>
      <div style="max-height:250px;overflow-y:auto">
        ${leads.map(l => `
          <div style="border:1px solid var(--border);border-radius:6px;padding:8px;margin-bottom:6px;font-size:12px">
            <strong>${l.type_travaux || 'Travaux'}</strong> — ${l.localisation || '—'}<br>
            Budget estimé : ${fmt(l.budget_estime)} · Notes : ${trunc(l.notes, 60)}
          </div>
        `).join('')}
      </div>`;
    window._odParams = { commune, code_dept: dept, limit };
  } catch (e) {
    if (el('od-results')) el('od-results').innerHTML = `<div class="alert alert-d">${e.message}</div>`;
  }
}

async function importOD() {
  if (!window._odParams) return;
  try {
    const result = await api('POST', '/leads/open-data/import', window._odParams);
    toast(`${result.imported} leads importés ✓`);
    closeModal();
    loadLeads();
  } catch (e) {
    toast('Erreur import : ' + e.message, 'err');
  }
}

// ─── AUTO-PROSPECTION ─────────────────────────────────────────────────────
async function showAutoProspect() {
  let status;
  try {
    status = await api('GET', '/leads/auto-prospect/status');
  } catch (e) {
    toast('Erreur statut : ' + e.message, 'err');
    return;
  }
  const last = status.last_result;
  openModal('⚙️ Auto-prospection (open data)',
    `<p style="font-size:13px;color:var(--text-muted);margin-bottom:12px">
       La veille tourne en tâche de fond : elle interroge l'open data Sitadel,
       déduplique, importe et qualifie automatiquement les leads à fort score.<br>
       <strong>Périmètre légal :</strong> open data uniquement — aucun scraping, aucun envoi automatique.</p>
     <div class="two-col" style="margin-bottom:12px">
       <div>
         <p><strong>État :</strong> ${status.enabled ? (status.running ? '🔄 Passage en cours…' : '🟢 Active') : '🔴 Désactivée (.env)'}</p>
         <p><strong>Dernier passage :</strong> ${status.last_run ? fmtDate(status.last_run) + ' ' + status.last_run.slice(11,16) : 'Jamais'}</p>
         <p><strong>Prochain passage :</strong> ${status.next_run ? fmtDate(status.next_run) + ' ' + status.next_run.slice(11,16) : '—'}</p>
       </div>
       <div>
         <p><strong>Total importé :</strong> ${status.total_imported} leads</p>
         ${last ? `<p><strong>Dernier résultat :</strong> ${last.fetched} récupérés, ${last.imported} importés, ${last.duplicates} doublons, ${last.auto_qualified} auto-qualifiés</p>` : ''}
       </div>
     </div>
     ${last?.errors?.length ? `<div class="alert alert-i"><span>ℹ️</span><span>${last.errors.join('<br>')}</span></div>` : ''}
     <div id="ap-result"></div>`,
    `<button class="btn btn-outline" onclick="closeModal()">Fermer</button>
     <button class="btn btn-primary" id="ap-run-btn" onclick="runAutoProspect()">▶️ Lancer un passage maintenant</button>`
  );
}

async function runAutoProspect() {
  const btn = el('ap-run-btn');
  btn.disabled = true; btn.innerHTML = '<span class="spin"></span> Passage en cours…';
  try {
    const data = await api('POST', '/leads/auto-prospect/run');
    const r = data.result;
    // La modal peut avoir été fermée pendant le passage (plusieurs secondes)
    if (!el('ap-result')) { toast(r ? `${r.imported} leads importés ✓` : data.message); loadLeads(); return; }
    el('ap-result').innerHTML = r
      ? `<div class="alert alert-s" style="margin-top:10px">✅ ${r.imported} nouveau(x) lead(s) importé(s) — ${r.duplicates} doublon(s) ignoré(s) — ${r.auto_qualified} auto-qualifié(s)</div>`
      : `<div class="alert alert-i" style="margin-top:10px">${data.message}</div>`;
    toast(`Auto-prospection : ${r ? r.imported + ' leads importés' : data.message} ✓`);
    loadLeads();
  } catch (e) {
    toast('Erreur : ' + e.message, 'err');
  } finally {
    btn.disabled = false; btn.innerHTML = '▶️ Lancer un passage maintenant';
  }
}

// ─── MODULE: ARTISANS ─────────────────────────────────────────────────────
async function loadArtisans() {
  el('artisans-table-body').innerHTML = '<tr><td colspan="9" style="padding:20px;text-align:center;color:var(--text-muted)">Chargement…</td></tr>';
  try {
    const params = new URLSearchParams();
    if (S.artisanFilters.contrat_signe) params.set('contrat_signe', S.artisanFilters.contrat_signe);
    const data = await api('GET', '/artisans/?' + params);
    S.artisans = data.artisans;
    renderArtisansTable(data.artisans);
  } catch (e) {
    toast('Erreur artisans : ' + e.message, 'err');
  }
}

function renderArtisansTable(artisans) {
  el('artisans-count').textContent = `${artisans.length} artisans`;
  const body = el('artisans-table-body');
  if (!artisans.length) {
    body.innerHTML = '<tr><td colspan="9"><div class="empty"><div class="empty-icon">🔨</div><p>Aucun artisan — ajoutez-en ou importez un CSV</p></div></td></tr>';
    return;
  }
  const payMap = { fiable: 'badge-fiable', retardataire: 'badge-retardataire', inconnu: 'badge-inconnu' };
  body.innerHTML = artisans.map(a => `
    <tr>
      <td><strong>${trunc(a.nom, 25)}</strong></td>
      <td>${a.metier ? `<span class="tag">${a.metier}</span>` : '—'}</td>
      <td>${a.ville || '—'}</td>
      <td>${a.siren || '—'}</td>
      <td>${scorePill(a.score_fiabilite)}</td>
      <td>${a.contrat_signe ? '<span class="badge badge-signe-contrat">Signé</span>' : '<span class="badge badge-nouveau">Non</span>'}</td>
      <td>${a.taux_commission ? a.taux_commission + '%' : '5%'}</td>
      <td>${badge(a.historique_paiement || 'inconnu', payMap)}</td>
      <td class="td-actions">
        <button class="btn btn-sm btn-outline" onclick="showArtisanForm(${a.id})" title="Modifier">✏️</button>
        <button class="btn btn-sm btn-secondary" onclick="enrichArtisan(${a.id})" title="Enrichir Sirene">🔍</button>
        <button class="btn btn-sm btn-primary" onclick="showGenerateMessage(${a.id})" title="Générer message">💬</button>
        <button class="btn btn-sm btn-success" onclick="generateContractFor(${a.id})" title="Créer contrat">📄</button>
        <button class="btn btn-sm btn-ghost" onclick="deleteArtisan(${a.id})" title="Supprimer">🗑</button>
      </td>
    </tr>
  `).join('');
}

function showArtisanForm(artisanId = null) {
  const a = artisanId ? S.artisans.find(x => x.id === artisanId) : null;
  const html = `
    <form id="artisan-form">
      <div class="form-row">
        <div class="form-group">
          <label>Nom / Raison sociale *</label>
          <input name="nom" value="${a?.nom || ''}" placeholder="SARL Martin BTP" required>
        </div>
        <div class="form-group">
          <label>Métier *</label>
          <input name="metier" value="${a?.metier || ''}" placeholder="Plombier, Électricien…">
        </div>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label>Ville</label>
          <input name="ville" value="${a?.ville || 'Rennes'}" placeholder="Rennes">
        </div>
        <div class="form-group">
          <label>SIREN (9 chiffres)</label>
          <input name="siren" value="${a?.siren || ''}" placeholder="123456789" maxlength="9">
          <p class="form-hint">Utilisé pour l'enrichissement Sirene automatique</p>
        </div>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label>Téléphone</label>
          <input name="telephone" value="${a?.telephone || ''}" placeholder="06 XX XX XX XX">
        </div>
        <div class="form-group">
          <label>Email</label>
          <input type="email" name="email" value="${a?.email || ''}" placeholder="contact@artisan.fr">
        </div>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label>Taux de commission (%)</label>
          <input type="number" name="taux_commission" value="${a?.taux_commission || '5'}" min="1" max="20" step="0.5">
        </div>
        <div class="form-group">
          <label>Historique paiement</label>
          <select name="historique_paiement">
            ${['inconnu', 'fiable', 'retardataire'].map(v => `<option value="${v}" ${(a?.historique_paiement || 'inconnu') === v ? 'selected' : ''}>${v.charAt(0).toUpperCase()+v.slice(1)}</option>`).join('')}
          </select>
        </div>
      </div>
      ${a ? `<div class="form-group">
        <label>Contrat signé</label>
        <select name="contrat_signe">
          <option value="0" ${!a.contrat_signe ? 'selected' : ''}>Non</option>
          <option value="1" ${a.contrat_signe ? 'selected' : ''}>Oui</option>
        </select>
      </div>` : ''}
      <div class="form-group">
        <label>Notes</label>
        <textarea name="notes" rows="2" placeholder="Notes internes…">${a?.notes || ''}</textarea>
      </div>
    </form>
  `;

  openDrawer(a ? 'Modifier l\'artisan' : 'Ajouter un artisan', html, async () => {
    const form = el('artisan-form');
    const fd = new FormData(form);
    const data = Object.fromEntries(fd.entries());
    data.taux_commission = parseFloat(data.taux_commission) || 5;
    if (data.contrat_signe !== undefined) data.contrat_signe = data.contrat_signe === '1';
    try {
      if (a) {
        await api('PUT', `/artisans/${a.id}`, data);
        toast('Artisan mis à jour ✓');
      } else {
        await api('POST', '/artisans/', data);
        toast('Artisan créé ✓');
      }
      closeDrawer();
      loadArtisans();
    } catch (e) {
      toast('Erreur : ' + e.message, 'err');
    }
  });
}

async function deleteArtisan(id) {
  if (!confirm('Supprimer cet artisan ?')) return;
  try {
    await api('DELETE', `/artisans/${id}`);
    toast('Artisan supprimé');
    loadArtisans();
  } catch (e) {
    toast('Erreur : ' + e.message, 'err');
  }
}

async function enrichArtisan(id) {
  const btn = document.querySelector(`[onclick="enrichArtisan(${id})"]`);
  if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spin"></span>'; }
  try {
    const result = await api('POST', `/artisans/${id}/enrich`);
    if (result.success) {
      toast(`Enrichi : ${result.fields_updated?.join(', ') || 'aucun champ nouveau'} ✓`);
      loadArtisans();
    } else {
      toast('Sirene : ' + result.error, 'warn');
    }
  } catch (e) {
    toast('Erreur enrichissement : ' + e.message, 'err');
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = '🔍'; }
  }
}

function showGenerateMessage(artisanId) {
  const a = S.artisans.find(x => x.id === artisanId);
  const html = `
    <div class="form-group">
      <label>Artisan</label>
      <div style="background:var(--bg);padding:10px;border-radius:7px;font-size:13px"><strong>${a?.nom}</strong> — ${a?.metier || ''} — ${a?.ville || ''}</div>
    </div>
    <div class="form-group">
      <label>Type de message</label>
      <select id="msg-type">
        <option value="email">Email (8-12 lignes)</option>
        <option value="sms">SMS (160 caractères)</option>
      </select>
    </div>
    <div id="msg-result" style="display:none">
      <div class="disclaimer">⚠️ DRAFT — À envoyer vous-même depuis votre messagerie.</div>
      <div class="section-title">Message généré</div>
      <div class="draft-box" id="msg-content"></div>
      <div style="margin-top:10px;display:flex;gap:8px">
        <button class="btn btn-outline btn-sm" onclick="copyDraft('msg-content')">📋 Copier</button>
      </div>
    </div>
  `;

  openDrawer(`💬 Message d'approche — ${a?.nom}`, html, async () => {
    const type = el('msg-type').value;
    const btn = el('drawer-save');
    btn.disabled = true; btn.innerHTML = '<span class="spin"></span> Génération…';
    try {
      const result = await api('POST', `/artisans/${artisanId}/generate-message`, { type_message: type });
      if (result.success) {
        el('msg-content').textContent = result.contenu;
        el('msg-result').style.display = 'block';
        toast('Message généré ✓');
      } else {
        toast('Erreur IA : ' + result.error, 'err');
      }
    } catch (e) {
      toast('Erreur : ' + e.message, 'err');
    } finally {
      btn.disabled = false; btn.textContent = 'Générer';
    }
  }, 'Générer');
}

async function generateContractFor(artisanId) {
  navigate('contracts');
  await showGenerateContract(artisanId);
}

function copyDraft(elemId) {
  const text = el(elemId)?.textContent;
  if (text && navigator.clipboard) {
    navigator.clipboard.writeText(text).then(() => toast('Copié dans le presse-papier ✓', 'info'));
  }
}

function showCSVImport() {
  openModal('⬇️ Import CSV Artisans',
    `<div class="form-hint" style="margin-bottom:12px">Colonnes attendues : <code>nom, metier, ville, siren, telephone, email</code><br>En-tête obligatoire, séparateur virgule ou point-virgule.</div>
     <div class="form-group">
       <label>Fichier CSV</label>
       <input type="file" id="csv-file" accept=".csv">
     </div>
     <div id="csv-result"></div>`,
    `<button class="btn btn-outline" onclick="closeModal()">Annuler</button>
     <button class="btn btn-primary" onclick="importCSV()">⬇️ Importer</button>`
  );
}

async function importCSV() {
  const fileInput = el('csv-file');
  if (!fileInput.files.length) { toast('Sélectionnez un fichier CSV', 'warn'); return; }
  const formData = new FormData();
  formData.append('file', fileInput.files[0]);
  try {
    const result = await api('POST', '/artisans/import-csv', formData, true);
    el('csv-result').innerHTML = `
      <div class="alert alert-s" style="margin-top:10px">✅ ${result.imported} artisan(s) importé(s)</div>
      ${result.errors.length ? `<div style="font-size:12px;color:var(--danger);margin-top:6px">${result.errors.join('<br>')}</div>` : ''}`;
    toast(`${result.imported} artisans importés ✓`);
    loadArtisans();
  } catch (e) {
    toast('Erreur import : ' + e.message, 'err');
  }
}

// ─── MODULE: CONTRATS ─────────────────────────────────────────────────────
async function loadContracts() {
  try {
    const data = await api('GET', '/contracts/');
    S.contracts = data.contracts;
    renderContractsTable(data.contracts);
  } catch (e) {
    toast('Erreur contrats : ' + e.message, 'err');
  }
}

function renderContractsTable(contracts) {
  el('contracts-count').textContent = `${contracts.length} contrats`;
  const body = el('contracts-table-body');
  const statMap = { brouillon: 'badge-brouillon', envoye: 'badge-envoye', signe: 'badge-signe-contrat' };
  if (!contracts.length) {
    body.innerHTML = '<tr><td colspan="7"><div class="empty"><div class="empty-icon">📄</div><p>Aucun contrat — générez-en depuis la fiche artisan</p></div></td></tr>';
    return;
  }
  body.innerHTML = contracts.map(c => `
    <tr>
      <td><strong>${c.artisan_nom}</strong></td>
      <td>${c.artisan_metier || '—'}</td>
      <td>${badge(c.statut, statMap)}</td>
      <td>${c.taux_commission ? c.taux_commission + '%' : '—'}</td>
      <td>${fmtDate(c.date_creation)}</td>
      <td>${c.date_signature ? fmtDate(c.date_signature) : '—'}</td>
      <td class="td-actions">
        ${c.fichier_docx ? `<a class="btn btn-sm btn-outline" href="/generated_docs/${c.fichier_docx.split('/').pop()}" target="_blank">⬇️ DOCX</a>` : ''}
        ${c.fichier_pdf ? `<a class="btn btn-sm btn-secondary" href="/generated_docs/${c.fichier_pdf.split('/').pop()}" target="_blank">⬇️ PDF</a>` : ''}
        ${c.statut !== 'signe' ? `<button class="btn btn-sm btn-success" onclick="signContract(${c.id})" title="Marquer signé">✍️ Signé</button>` : ''}
        ${c.statut === 'brouillon' ? `<button class="btn btn-sm btn-info" onclick="sendContract(${c.id})">📤 Envoyé</button>` : ''}
        <button class="btn btn-sm btn-ghost" onclick="deleteContract(${c.id})">🗑</button>
      </td>
    </tr>
  `).join('');
}

async function showGenerateContract(artisanId = null) {
  await loadArtisans();
  const artisanOpts = S.artisans.map(a =>
    `<option value="${a.id}" ${artisanId === a.id ? 'selected' : ''}>${a.nom} — ${a.metier || ''} — ${a.ville || ''}</option>`
  ).join('');

  const html = `
    <div class="disclaimer">⚠️ MODÈLE À FAIRE VALIDER PAR UN PROFESSIONNEL DU DROIT — Document indicatif.</div>
    <div class="form-group">
      <label>Artisan</label>
      <select id="gen-artisan">${artisanOpts}</select>
    </div>
    <div class="form-group">
      <label>Taux de commission (%)</label>
      <input type="number" id="gen-taux" value="5" min="1" max="20" step="0.5">
      <p class="form-hint">Laissez vide pour utiliser le taux de la fiche artisan</p>
    </div>
    <div id="gen-result" style="display:none"></div>
  `;

  openDrawer('📄 Générer un contrat', html, async () => {
    const artisan_id = parseInt(el('gen-artisan').value);
    const taux = parseFloat(el('gen-taux').value);
    const btn = el('drawer-save');
    btn.disabled = true; btn.innerHTML = '<span class="spin"></span> Génération…';
    try {
      const result = await api('POST', `/contracts/${artisan_id}/generate?taux_commission=${taux}`);
      el('gen-result').style.display = 'block';
      el('gen-result').innerHTML = `
        <div class="alert alert-s">✅ Contrat généré pour ${result.contract.artisan_id}</div>
        <div style="display:flex;gap:8px;margin-top:8px">
          ${result.docx_url ? `<a class="btn btn-outline" href="${result.docx_url}" target="_blank">⬇️ Télécharger DOCX</a>` : ''}
          ${result.pdf_url ? `<a class="btn btn-secondary" href="${result.pdf_url}" target="_blank">⬇️ Télécharger PDF</a>` : ''}
        </div>
        ${result.warnings?.length ? `<div style="font-size:12px;color:var(--warning);margin-top:6px">⚠️ ${result.warnings.join('<br>')}</div>` : ''}`;
      toast('Contrat généré ✓');
      loadContracts();
    } catch (e) {
      toast('Erreur génération : ' + e.message, 'err');
    } finally {
      btn.disabled = false; btn.textContent = 'Générer';
    }
  }, 'Générer DOCX + PDF');
}

async function signContract(id) {
  try {
    await api('PUT', `/contracts/${id}/status`, { statut: 'signe' });
    toast('Contrat marqué signé ✓');
    loadContracts();
    loadArtisans();
  } catch (e) {
    toast('Erreur : ' + e.message, 'err');
  }
}

async function sendContract(id) {
  try {
    await api('PUT', `/contracts/${id}/status`, { statut: 'envoye' });
    toast('Contrat marqué envoyé');
    loadContracts();
  } catch (e) {
    toast('Erreur : ' + e.message, 'err');
  }
}

async function deleteContract(id) {
  if (!confirm('Supprimer ce contrat et ses fichiers ?')) return;
  try {
    await api('DELETE', `/contracts/${id}`);
    toast('Contrat supprimé');
    loadContracts();
  } catch (e) {
    toast('Erreur : ' + e.message, 'err');
  }
}

// ─── MODULE: COMMISSIONS ─────────────────────────────────────────────────
async function loadCommissions() {
  try {
    const [commData, statsData] = await Promise.all([
      api('GET', '/crm/commissions'),
      api('GET', '/dashboard/commissions-summary'),
    ]);
    S.commissions = commData.commissions;
    renderCommissionsTable(commData.commissions);
    renderCommissionsSummary(statsData);
  } catch (e) {
    toast('Erreur commissions : ' + e.message, 'err');
  }
}

function renderCommissionsTable(commissions) {
  el('commissions-count').textContent = `${commissions.length} commissions`;
  const body = el('commissions-table-body');
  if (!commissions.length) {
    body.innerHTML = '<tr><td colspan="8"><div class="empty"><div class="empty-icon">💰</div><p>Aucune commission — créez-en depuis un lead signé</p></div></td></tr>';
    return;
  }
  const today = new Date().toISOString().split('T')[0];
  body.innerHTML = commissions.map(c => {
    const isLate = c.statut === 'en_attente' && c.date_echeance && c.date_echeance < today;
    const statut = isLate ? 'en_retard' : c.statut;
    return `
      <tr ${isLate ? 'style="background:#fff1f2"' : ''}>
        <td><strong>${c.artisan_nom || '—'}</strong></td>
        <td>${trunc(c.type_travaux, 22) || '—'}</td>
        <td><strong>${fmt(c.montant)}</strong><br><span style="font-size:11px;color:var(--text-muted)">${c.taux}% de ${fmt(c.montant_chantier)}</span></td>
        <td>${c.date_echeance ? `<span ${isLate ? 'style="color:var(--danger);font-weight:700"' : ''}>${fmtDate(c.date_echeance)}</span>` : '—'}</td>
        <td>${badge(statut, STATUT_COMM)}</td>
        <td>${c.relances_count || 0}/${c.derniere_relance ? fmtDate(c.derniere_relance) : '—'}</td>
        <td class="td-actions">
          ${c.statut !== 'payee' ? `<button class="btn btn-sm btn-success" onclick="markPaid(${c.id})">✅ Payée</button>` : ''}
          ${c.statut !== 'payee' ? `
            <button class="btn btn-sm btn-warning" onclick="showRelance(${c.id}, 1)" title="J+30 amiable">R1</button>
            <button class="btn btn-sm btn-warning" onclick="showRelance(${c.id}, 2)" title="J+45 ferme">R2</button>
            <button class="btn btn-sm btn-danger" onclick="showRelance(${c.id}, 3)" title="J+60 MED">MED</button>
          ` : ''}
        </td>
      </tr>
    `;
  }).join('');
}

function renderCommissionsSummary(stats) {
  el('total-encaisse').textContent = fmt(stats.total_encaisse);
  el('total-pipeline').textContent = fmt(stats.total_pipeline);

  // Chart mensuel simple
  const chart = el('monthly-chart');
  const months = stats.by_month || [];
  if (months.length) {
    const max = Math.max(...months.map(m => m.montant)) || 1;
    chart.innerHTML = `<div class="section-title">CA mensuel (commissions encaissées)</div>
      <div style="display:flex;align-items:flex-end;gap:8px;height:80px">
        ${months.slice(0, 12).reverse().map(m => `
          <div style="flex:1;display:flex;flex-direction:column;align-items:center;gap:2px">
            <div style="flex:1;width:100%;display:flex;align-items:flex-end">
              <div style="width:100%;background:var(--accent);opacity:.8;border-radius:3px 3px 0 0;height:${Math.round((m.montant/max)*60)+4}px" title="${fmt(m.montant)}"></div>
            </div>
            <div style="font-size:9px;color:var(--text-muted)">${m.mois?.slice(5)}</div>
          </div>
        `).join('')}
      </div>`;
  }
}

async function markPaid(id) {
  if (!confirm('Marquer cette commission comme payée ?')) return;
  try {
    await api('PUT', `/crm/commissions/${id}/status`, { statut: 'payee' });
    toast('Commission marquée payée ✓');
    loadCommissions();
  } catch (e) {
    toast('Erreur : ' + e.message, 'err');
  }
}

async function showRelance(commissionId, niveau) {
  const labels = { 1: 'Relance amiable (J+30)', 2: 'Relance ferme (J+45)', 3: 'Mise en demeure (J+60)' };
  const html = `
    <div class="disclaimer">⚠️ DRAFT — À envoyer vous-même depuis votre client mail.</div>
    <p style="font-size:13px;margin-bottom:12px">Génération d'un <strong>${labels[niveau]}</strong> par l'IA.</p>
    <div id="relance-result" style="text-align:center;color:var(--text-muted)">Cliquez sur "Générer" pour créer le message…</div>
  `;
  openDrawer(labels[niveau], html, async () => {
    const btn = el('drawer-save');
    btn.disabled = true; btn.innerHTML = '<span class="spin"></span> Génération…';
    try {
      const result = await api('POST', `/crm/commissions/${commissionId}/relance?niveau=${niveau}`);
      el('relance-result').innerHTML = `
        <div class="draft-box">${result.contenu}</div>
        <div style="margin-top:8px;display:flex;gap:6px">
          <button class="btn btn-sm btn-outline" onclick="copyDraft('relance-draft')">📋 Copier</button>
        </div>
        <div id="relance-draft" style="display:none">${result.contenu}</div>`;
      // Copy to clipboard
      if (navigator.clipboard) {
        await navigator.clipboard.writeText(result.contenu);
        toast('Draft copié dans le presse-papier', 'info');
      }
      toast('Relance générée ✓');
      loadCommissions();
    } catch (e) {
      toast('Erreur : ' + e.message, 'err');
    } finally {
      btn.disabled = false; btn.textContent = 'Générer';
    }
  }, 'Générer');
}

async function showAddCommission() {
  await Promise.all([loadLeads(), loadArtisans()]);
  const leadOpts = S.leads.filter(l => ['signe', 'transmis', 'devis_envoye'].includes(l.statut)).map(l =>
    `<option value="${l.id}">${l.type_travaux || 'Travaux'} — ${l.contact_nom || '—'} (${l.statut})</option>`
  ).join('');
  const artisanOpts = S.artisans.map(a =>
    `<option value="${a.id}">${a.nom} — ${a.metier || ''}</option>`
  ).join('');

  const html = `
    <form id="comm-form">
      <div class="form-group"><label>Lead *</label><select name="lead_id">${leadOpts}</select></div>
      <div class="form-group"><label>Artisan *</label><select name="artisan_id">${artisanOpts}</select></div>
      <div class="form-row">
        <div class="form-group">
          <label>Montant chantier HT (€) *</label>
          <input type="number" name="montant_chantier" placeholder="15000" min="0" required>
        </div>
        <div class="form-group">
          <label>Taux commission (%)</label>
          <input type="number" name="taux" value="5" min="1" max="20" step="0.5">
        </div>
      </div>
      <div class="form-group">
        <label>Date d'échéance</label>
        <input type="date" name="date_echeance">
        <p class="form-hint">Laissez vide = J+30 à partir d'aujourd'hui</p>
      </div>
      <div class="form-group"><label>Notes</label><textarea name="notes" rows="2"></textarea></div>
    </form>
  `;

  openDrawer('Enregistrer une commission', html, async () => {
    const form = el('comm-form');
    const fd = new FormData(form);
    const data = Object.fromEntries(fd.entries());
    data.lead_id = parseInt(data.lead_id);
    data.artisan_id = parseInt(data.artisan_id);
    data.montant_chantier = parseFloat(data.montant_chantier);
    data.taux = parseFloat(data.taux) || 5;
    try {
      await api('POST', '/crm/commissions', data);
      toast('Commission enregistrée ✓');
      closeDrawer();
      loadCommissions();
    } catch (e) {
      toast('Erreur : ' + e.message, 'err');
    }
  });
}

async function generateRelanceFromAlert(commissionId) {
  navigate('commissions');
  await showRelance(commissionId, 1);
}

// ─── MODULE: CHAT ─────────────────────────────────────────────────────────
async function sendChat() {
  const input = el('chat-input');
  const msg = input.value.trim();
  if (!msg) return;

  addChatMessage('user', msg);
  S.chatHistory.push({ role: 'user', content: msg });
  input.value = '';

  const thinking = addChatMessage('assistant', '…', 'msg-thinking');
  el('chat-send').disabled = true;

  try {
    const result = await api('POST', '/ai/chat', {
      message: msg,
      history: S.chatHistory.slice(-10),
    });
    thinking.remove();
    const response = result.response || result.error || 'Erreur IA';
    addChatMessage('assistant', response);
    S.chatHistory.push({ role: 'assistant', content: response });
  } catch (e) {
    thinking.remove();
    addChatMessage('assistant', '⚠️ Erreur : ' + e.message);
  } finally {
    el('chat-send').disabled = false;
    input.focus();
  }
}

function addChatMessage(role, content, extraClass = '') {
  const msgs = el('chat-messages');
  const div = document.createElement('div');
  div.className = `msg msg-${role} ${extraClass}`;
  div.textContent = content;
  msgs.appendChild(div);
  msgs.scrollTop = msgs.scrollHeight;
  return div;
}

function quickChat(text) {
  el('chat-input').value = text;
  sendChat();
}

async function estimateChantier() {
  const desc = prompt('Décrivez le chantier (type de travaux, surface, localisation) :');
  if (!desc) return;
  try {
    const result = await api('POST', '/ai/estimate-chantier', { description: desc });
    if (result.success) {
      const d = result.data;
      openModal('💰 Estimation du chantier',
        `<div class="three-col">
          <div class="stat-card success"><div class="lbl">Min</div><div class="val">${fmt(d.estimation_min)}</div></div>
          <div class="stat-card accent"><div class="lbl">Estimation</div><div class="val">${fmt(d.estimation_centrale)}</div></div>
          <div class="stat-card"><div class="lbl">Max</div><div class="val">${fmt(d.estimation_max)}</div></div>
        </div>
        <div style="margin-top:14px">
          <p><strong>Type :</strong> ${d.type_travaux}</p>
          <p><strong>Commission 5% :</strong> ${fmt(d.commission_5pct)}</p>
          <p><strong>Hypothèses :</strong> ${d.hypotheses}</p>
          <p><strong>Fiabilité :</strong> <span class="tag">${d.fiabilite}</span></p>
        </div>`,
        `<button class="btn btn-outline" onclick="closeModal()">Fermer</button>`
      );
    }
  } catch (e) {
    toast('Erreur estimation : ' + e.message, 'err');
  }
}

// ─── INIT ──────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  // Navigation
  document.querySelectorAll('.nav-item[data-mod]').forEach(item => {
    item.addEventListener('click', () => navigate(item.dataset.mod));
  });

  // Drawer close
  document.getElementById('drawer-close').addEventListener('click', closeDrawer);
  document.getElementById('drawer-overlay').addEventListener('click', closeDrawer);

  // Modal close
  document.getElementById('modal-close').addEventListener('click', closeModal);
  document.getElementById('modal-overlay').addEventListener('click', e => {
    if (e.target === e.currentTarget) closeModal();
  });

  // Chat enter key
  el('chat-input').addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); }
  });

  // Lead filters
  el('filter-statut').addEventListener('change', e => {
    S.leadFilters.statut = e.target.value;
    loadLeads();
  });
  el('filter-score').addEventListener('change', e => {
    S.leadFilters.score_min = e.target.value;
    loadLeads();
  });

  // Artisan filter
  el('filter-contrat').addEventListener('change', e => {
    S.artisanFilters.contrat_signe = e.target.value;
    loadArtisans();
  });

  // Auto-refresh alerts every 5 min
  setInterval(() => {
    api('GET', '/crm/alerts').then(data => {
      const count = data.alerts.length;
      const b = el('alert-badge');
      if (b) { b.textContent = count; b.style.display = count ? '' : 'none'; }
    }).catch(() => {});
  }, 300000);

  // Start on dashboard
  navigate('dashboard');
});
