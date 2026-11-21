import {query, readInput, encodeInput} from './api.js';
import {el, table} from './table.js';

const byId = id => document.getElementById(id);
const batchPanel = byId('notice-batch');
const filesHost = byId('notice-files');
const message = byId('notice-message');
const uploaded = new Map(); // row element -> {name, text, bytes}
let current = null;

function say(text, bad = false) {
  message.value = text;
  message.classList.toggle('problem', bad);
}

function fileRow(index = '') {
  const row = el('div', undefined, 'notice-file');
  const label = el('label');
  label.append(el('span', `楼栋 ${index || ''}`));
  const name = el('input');
  name.type = 'text';
  name.maxLength = 120;
  name.placeholder = '来源名称，如：一号楼第三批';
  const pick = el('input');
  pick.type = 'file';
  pick.accept = '.csv,text/csv';
  const text = el('textarea');
  text.rows = 3;
  text.placeholder = '或粘贴送审 CSV';
  const remove = el('button', '移除', 'btn');
  remove.type = 'button';
  pick.addEventListener('change', async () => {
    const file = pick.files[0];
    if (!file) return;
    try {
      const [decoded, bytes] = await readInput(file);
      text.value = decoded;
      if (!name.value) name.value = file.name;
      uploaded.set(row, {text: decoded, bytes});
    } catch (error) {
      pick.value = '';
      say(error.message, true);
    }
  });
  text.addEventListener('input', () => {
    const kept = uploaded.get(row);
    if (kept && kept.text !== text.value) uploaded.delete(row);
  });
  remove.addEventListener('click', () => {
    uploaded.delete(row);
    row.remove();
    renumber();
  });
  label.append(name, pick);
  row.append(label, text, remove);
  filesHost.append(row);
  renumber();
  return row;
}

function renumber() {
  [...filesHost.children].forEach((row, i) => {
    row.querySelector('label span').textContent = `楼栋 ${i + 1}`;
  });
}

function collectFiles() {
  const names = new Set();
  const sources = [];
  for (const row of filesHost.children) {
    const name = row.querySelector('input[type=text]').value.trim();
    const text = row.querySelector('textarea').value;
    const kept = uploaded.get(row);
    if (!text && !kept) {
      throw Error('每份送审文件都需要上传或粘贴内容');
    }
    const label = name || `第 ${sources.length + 1} 批送审`;
    if (names.has(label)) throw Error(`送审文件名称重复：${label}`);
    names.add(label);
    const entry = {name: label};
    if (kept && kept.text === text) entry.data_base64 = encodeInput(kept.bytes);
    else entry.data = text;
    sources.push(entry);
  }
  if (!sources.length) throw Error('至少添加一份楼栋送审文件');
  return sources;
}

function collectBook() {
  const pick = byId('notice-book-file');
  const file = pick.files[0];
  if (!file) return {};
  return {book_base64: encodeInput(file)};
}

function outcomeTag(value, code) {
  if (!value) return el('span', code || '阻断', 'state problem');
  return el('span', value, value === '通过' ? 'state' : 'state problem');
}

function renderMotions(report) {
  const host = byId('notice-motions');
  if (!report.motions.length) {
    host.replaceChildren(el('p', '本批没有可汇总的议案', 'empty'));
    return;
  }
  const columns = [
    ['表决议案', 'key'],
    ['采用来源', row => {
      const adopted = row.adopted;
      const cell = el('div');
      if (!adopted) {
        cell.append(el('span', '无采信修订', 'state problem'));
        return cell;
      }
      cell.append(el('div', `${adopted.source_id || '—'} · 修订 ${adopted.revision} · 行 ${adopted.line}`));
      const detail = el('small', `参与 ${adopted.participation_owners} 人 / ${adopted.participation_area} ㎡，赞成 ${adopted.yes_owners} 人 / ${adopted.yes_area} ㎡`);
      cell.append(detail);
      return cell;
    }],
    ['结论', row => outcomeTag(row.adopted?.outcome)],
    ['补传前后', row => {
      const cell = el('div');
      const flag = el('span', row.conclusion_changed ? '结论变化' : '无变化',
        row.conclusion_changed ? 'state problem' : 'state');
      cell.append(flag);
      const trail = el('details');
      trail.append(el('summary', `送审 ${row.submission_count} 次 / 修订 ${row.history.length} 版`));
      const list = el('ul');
      for (const item of row.history) {
        const li = el('li', `修订 ${item.revision}：${item.outcome || '阻断（' + (item.blocked_code || '') + '）'}${item.changed ? ' · 结论翻转' : ''}`);
        list.append(li);
      }
      trail.append(list);
      cell.append(trail);
      return cell;
    }],
  ];
  table(host, columns, report.motions);
}

function renderSources(report) {
  const host = byId('notice-sources');
  const rows = report.file_details.map(item => ({
    id: item.index,
    name: item.name,
    hash: item.sha256.slice(0, 12),
    encoding: item.encoding,
    bytes: item.bytes,
  }));
  table(host, [
    ['#', 'id', 'num'], ['来源名称', 'name'], ['编码', 'encoding'],
    ['字节', 'bytes', 'num'], ['摘要', 'hash'],
  ], rows);
}

async function loadHistory() {
  const history = await query('/api/notices');
  return history;
}

function renderActions(report) {
  const host = byId('notice-actions');
  host.replaceChildren();
  const meta = el('p', `批次指纹 ${report.manifest.notice_id.slice(0, 12)}… · 来源 ${report.counts.sources} 份 · 议案 ${report.motions.length} 个`);
  host.append(meta);
  const actions = el('div', undefined, 'actions');
  if (!report.sealed) {
    const seal = el('button', '封存此公示批次', 'btn btn--primary');
    seal.type = 'button';
    seal.addEventListener('click', async () => {
      seal.disabled = true;
      try {
        const updated = await query(`/api/notices/${current.manifest.notice_id}/seal`, {});
        say('批次已封存；后续更高修订须重新确认');
        await show(report.manifest.notice_id);
      } catch (error) {
        say(error.message, true);
      } finally {
        seal.disabled = false;
      }
    });
    actions.append(seal);
  } else {
    host.append(el('p', `已于 ${report.sealed_at.slice(0, 19).replace('T', ' ')} UTC 封存，原送审文件原样保留`, 'state'));
    const amend = el('button', '评估补传的更高修订', 'btn btn--primary');
    amend.type = 'button';
    amend.addEventListener('click', assessAmendment);
    actions.append(amend);
  }
  host.append(actions);
}

async function assessAmendment() {
  let sources;
  try {
    sources = collectFiles();
  } catch (error) {
    say(error.message, true);
    return;
  }
  try {
    const assessment = await query(`/api/notices/${current.manifest.notice_id}/amendments`,
      {sources, ...collectBook()});
    renderAssessment(assessment);
  } catch (error) {
    say(error.message, true);
  }
}

function renderAssessment(assessment) {
  const host = byId('notice-motions');
  const wrap = el('div');
  const head = el('h3', '封存后补传影响面（确认前不形成新公示）');
  wrap.append(head);
  if (!assessment.would_change) {
    wrap.append(el('p', '补传未带来更高修订或任何差异，无需新公示。', 'empty'));
  }
  if (assessment.affected.length) {
    const columns = [
      ['表决议案', 'key'],
      ['修订变化', row => `${row.previous_revision ?? '—'} → ${row.candidate_revision}`],
      ['结论', row => el('span',
        `${row.before?.outcome ?? '—'} → ${row.after.outcome}`,
        row.conclusion_changed ? 'state problem' : 'state')],
      ['差异字段', row => el('small', row.field_changes.map(c => `${c.field}: ${c.before} → ${c.after}`).join('；') || '仅来源变化')],
    ];
    table(wrap, columns, assessment.affected);
  }
  if (assessment.blocked.length) {
    wrap.append(el('h4', `无法采信的更高修订（${assessment.blocked.length}）`));
    const columns = [
      ['表决议案', 'key'],
      ['候选修订', 'candidate_revision', 'num'],
      ['阻断原因', row => el('small', row.reasons.map(r => `${r.code}（行 ${r.line}）`).join('；'))],
    ];
    table(wrap, columns, assessment.blocked);
  }
  if (assessment.would_change) {
    const confirm = el('button', '重新确认并形成新公示批次', 'btn btn--primary');
    confirm.type = 'button';
    confirm.addEventListener('click', async () => {
      confirm.disabled = true;
      try {
        const sources = collectFiles();
        const next = await query(`/api/notices/${assessment.notice_id}/confirm`,
          {sources, ...collectBook()});
        current = next;
        paint(next);
        say('已形成新公示批次，封存批次原样保留');
      } catch (error) {
        say(error.message, true);
      } finally {
        confirm.disabled = false;
      }
    });
    wrap.append(confirm);
  }
  host.replaceChildren(wrap);
}

function paint(report) {
  current = report;
  byId('notice-id').textContent = report.manifest.notice_id.slice(0, 12);
  byId('notice-id').title = report.manifest.notice_id;
  const state = byId('notice-state');
  state.textContent = report.sealed ? '已封存' : '待封存';
  state.className = report.sealed ? 'state problem' : 'state';
  byId('notice-summary').textContent = `${report.counts.accepted} 采信 / ${report.counts.rejected} 隔离 / ${report.counts.suppressed} 替代`;
  renderMotions(report);
  renderSources(report);
  renderActions(report);
}

async function show(noticeId) {
  const report = await query(`/api/notices/${noticeId}`);
  paint(report);
}

export function initNoticeBatch(open) {
  batchPanel.hidden = !open;
  if (!open) return;
  if (!filesHost.children.length) fileRow();
}

byId('notice-add').addEventListener('click', () => fileRow());
byId('notice-form').addEventListener('submit', async event => {
  event.preventDefault();
  let sources;
  try {
    sources = collectFiles();
  } catch (error) {
    say(error.message, true);
    return;
  }
  try {
    say('合并计算中…');
    const report = await query('/api/notices', {sources, ...collectBook()});
    paint(report);
    say('公示批次已生成；同组文件重跑不会新增批次');
  } catch (error) {
    say(error.message, true);
  }
});
