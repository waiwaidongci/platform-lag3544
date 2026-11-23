import {plot} from '../components/common/chart.js';
import {feedback, field} from '../components/common/fields.js';
import {empty, metrics, panel, pill} from '../components/common/panels.js';
import {table} from '../components/common/table.js';
import {SWAPSTATE} from '../constants/enums.js';
import {handler} from '../hooks/action.js';
import {session} from '../stores/session.js';
import {workspace} from '../stores/workspace.js';
import {button, el, h, link, p} from '../utils/dom.js';
import {date} from '../utils/format.js';

let station = '';
let previewId = null;

function batchPanel(conf, batches, refresh) {
  const error = feedback();
  const sample = button('下载示例 CSV', {class:'quiet', onClick:event =>
    handler(sample, error, () => workspace.download('/swap/template', conf.sample_name))(event)});
  const submit = button('校验并导入', {type:'submit', class:'primary'});
  const upload = session.canWrite && el('form', {class:'fields', onSubmit:handler(submit, error, async event => {
    const data = new FormData(event.target);
    const file = data.get('source');
    if (!file?.size) throw new Error('请选择一个 CSV 文件');
    if (file.size > 2_000_000) throw new Error('CSV 最多 2 MB');
    const item = await workspace.uploadCalibration({name:data.get('batch_name'), filename:file.name, csv_text:await file.text()});
    error.textContent = item.voided ? `已导入，同时作废 ${item.voided} 条未发布判定。` : '已导入。';
    previewId = item.id;
    await refresh();
  })}, field({key:'batch_name', label:'批次名称', type:'string', max_length:120}),
    el('label', {class:'field', for:'source'}, el('span', {}, '标定 CSV'),
      el('input', {id:'source', type:'file', name:'source', accept:'.csv,text/csv', required:true})), submit);
  const list = table([
    {label:'批次', render:row => link(row.name, `#swap`, {onClick:event => {event.preventDefault(); previewId = row.id; refresh();}})},
    {key:'station', label:'车站'},
    {label:'通道', render:row => row.channels.join('、')},
    {key:'row_count', label:'行数'},
    {label:'导入时间', render:row => date(row.created_at)},
  ], batches, {caption:'标定批次', empty:'还没有标定批次，请导入示例或业务 CSV。'});
  return panel('标定批次', p('导入后保留数据指纹；新批次入库会使该站未发布的判定作废。', 'subtle'),
    el('div', {class:'actions'}, sample), upload, error, list);
}

async function previewPanel(batches, refresh) {
  if (!batches.length) return null;
  const selected = batches.find(item => item.id === previewId) || batches[0];
  previewId = selected.id;
  const detail = await workspace.swapBatch(selected.id);
  return panel('批次明细预览', el('div', {class:'actions'},
    el('label', {for:'batch-id', class:'sr'}, '选择标定批次'),
    el('select', {id:'batch-id', 'aria-label':'选择标定批次', onChange:event => {previewId = Number(event.target.value); refresh();}},
      batches.map(item => el('option', {value:item.id, selected:item.id === selected.id}, item.name)))),
    p(`${detail.filename} · ${detail.row_count} 行 · 指纹 ${detail.checksum.slice(0, 12)}…`, 'filename'),
    table([{key:'station', label:'车站'}, {key:'channel', label:'通道'}, {key:'timestamp', label:'采样时间'},
      {key:'level_dba', label:'声级（dB(A)）'}], detail.rows, {caption:'批次明细预览', pageSize:16}),
    detail.row_count > detail.rows.length && p(`仅预览前 ${detail.rows.length} 行，完整数据以导入的 CSV 为准。`, 'subtle'));
}

function tonePanel(periods, stations, refresh) {
  const error = feedback();
  const picker = el('label', {class:'field', for:'tone-station'}, el('span', {}, '车站'),
    el('select', {id:'tone-station', onChange:event => {station = event.target.value; refresh();}},
      stations.map(name => el('option', {value:name, selected:name === station}, name))));
  const submit = button('补录试音时段', {type:'submit', class:'primary'});
  const form = session.canWrite && el('form', {class:'fields', onSubmit:handler(submit, error, async event => {
    const data = new FormData(event.target);
    const item = await workspace.addTonePeriod({station, point:data.get('point'), start:data.get('start'), end:data.get('end')});
    error.textContent = item.created
      ? (item.voided ? `已补录，同时作废 ${item.voided} 条未发布判定。` : '已补录。')
      : '相同时段已存在，未重复补录。';
    await refresh();
  })}, field({key:'point', label:'测点', type:'string', max_length:120}),
    field({key:'start', label:'试音开始（YYYY-MM-DD HH:MM:SS）', type:'string', max_length:19}),
    field({key:'end', label:'试音结束（YYYY-MM-DD HH:MM:SS）', type:'string', max_length:19}), submit);
  const list = table([
    {key:'point', label:'测点'}, {key:'start', label:'开始'}, {key:'end', label:'结束'},
    {key:'author', label:'补录人'},
    ...(session.canWrite ? [{label:'操作', render:row => {
      const remove = button('删除', {class:'quiet'});
      remove.addEventListener('click', handler(remove, error, async () => {
        const result = await workspace.removeTonePeriod(row.id);
        error.textContent = result.voided ? `已删除，同时作废 ${result.voided} 条未发布判定。` : '已删除。';
        await refresh();
      }));
      return remove;
    }}] : []),
  ], periods, {caption:'试音时段', empty:'该站还没有试音时段，请先补录。'});
  return panel('试音时段', p('不同测点的并发补录各自成行，都会保留；增删时段会使该站未发布的判定作废。', 'subtle'),
    stations.length ? picker : null, form, error, list);
}

function determinationView(item, refresh) {
  const message = feedback();
  const result = item.result;
  const actions = el('div', {class:'actions'}, pill(SWAPSTATE[item.state], item.state));
  if (item.state === 'computed' && session.canReview) {
    const publish = button('发布到交班页面', {class:'primary', 'data-testid':'publish'});
    publish.addEventListener('click', handler(publish, message, async () => {
      await workspace.publishDetermination(item.id);
      await refresh();
    }));
    actions.append(publish);
  }
  if (item.publication) {
    const download = button('下载交班 CSV', {class:'quiet'});
    download.addEventListener('click', handler(download, message, () =>
      workspace.download(`/swap/determinations/${item.id}/export`, `swap-handover-${item.station}-v${item.version}.csv`)));
    actions.append(download, p(`已于 ${date(item.publication.created_at)} 发布`, 'subtle'));
  }
  if (item.state === 'void') actions.append(p('数据已更新，本版判定作废，请重新判定。', 'subtle'));
  return el('section', {class:'analysis', 'data-testid':'determination'},
    el('div', {class:'result-head'}, p(`${item.station} · 第 ${item.version} 版`, 'eyeline'),
      h(2, result.headline), p(result.note, 'intro-copy'), actions, message),
    metrics(result.metrics),
    result.charts.map(plot),
    (result.sections || []).map(section => panel(section.title, p(section.text))),
    result.tables.map(item => panel(item.title, table(item.columns, item.rows, {caption:item.title}))));
}

function determinePanel(conf, determinations, selected, refresh) {
  const error = feedback();
  const submit = button('执行判定', {type:'submit', class:'primary', 'data-testid':'determine'});
  const form = session.canWrite && el('form', {class:'fields', onSubmit:handler(submit, error, async event => {
    const data = new FormData(event.target);
    const params = Object.fromEntries(conf.params.map(param => [param.key, data.get(param.key)]));
    const item = await workspace.determine({station, params});
    location.hash = `#swap/${item.id}`;
  })}, el('div', {class:'form-grid'}, conf.params.map(param => field(param))), el('div', {class:'actions'}, submit));
  const list = table([
    {label:'判定', render:row => link(`第 ${row.version} 版 · #${row.id}`, `#swap/${row.id}`)},
    {label:'状态', render:row => pill(SWAPSTATE[row.state], row.state)},
    {key:'author', label:'判定人'},
    {label:'时间', render:row => date(row.created_at)},
  ], determinations, {caption:'判定记录', empty:'还没有判定记录，请设置参数后执行。'});
  return panel('接反判定', p('整站配法共用一档校时偏移；试音时段内读数低于门槛才排除，缺测不排除。', 'subtle'),
    form, error, list, selected && determinationView(selected, refresh));
}

export async function swapPage(route, refresh) {
  const {spec} = workspace;
  const conf = spec.swap;
  const [batches, periods, determinations] = await Promise.all(
    [workspace.swapBatches(), workspace.tonePeriods(), workspace.determinations()]);
  const stations = [...new Set([...batches.map(item => item.station), ...periods.map(item => item.station),
    ...determinations.map(item => item.station)])];
  if (!stations.includes(station)) station = stations[0] || '';
  const scopedPeriods = periods.filter(item => item.station === station);
  const scopedDeterminations = determinations.filter(item => item.station === station);
  const selected = route.id ? await workspace.determination(route.id) : null;
  const preview = await previewPanel(batches, refresh);
  return el('div', {class:'two-col'},
    el('div', {class:'wide-panel'},
      batchPanel(conf, batches, refresh),
      preview,
      station ? tonePanel(scopedPeriods, stations, refresh)
        : panel('试音时段', empty('请先导入标定批次，再补录试音时段。')),
      station && determinePanel(conf, scopedDeterminations, selected, refresh)),
    el('aside', {class:'sidebar-panel'},
      panel('核查口径', el('ul', {class:'method-list'}, conf.methodology.map(text => el('li', {}, text)))),
      panel('字段说明', el('dl', {class:'dictionary'}, conf.fields.map(item => el('div', {}, el('dt', {}, item.label),
        el('dd', {}, item.key, item.required === false ? ' · 可空' : ' · 必填'))))),
      panel('交班确认', p('交班页面只确认所有可行配法共有的接线；无解时列出冲突通道。', 'subtle'),
        link('查看交班与导出', '#delivery', {class:'quiet'}))));
}
