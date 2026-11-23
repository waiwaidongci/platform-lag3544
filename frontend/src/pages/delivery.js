import {feedback} from '../components/common/fields.js';
import {panel, pill} from '../components/common/panels.js';
import {table} from '../components/common/table.js';
import {REVIEW} from '../constants/enums.js';
import {handler} from '../hooks/action.js';
import {workspace} from '../stores/workspace.js';
import {button, el, h, link, p} from '../utils/dom.js';
import {date} from '../utils/format.js';
import {runPage} from './run.js';

function wiringPanel(handovers) {
  if (!handovers.length) return panel('通道接线确认', p('还没有已发布的通道判定，发布后将在此确认共有接线。', 'empty'));
  const blocks = handovers.map(entry => {
    const children = [p(entry.headline, 'intro-copy')];
    if (entry.confirmed.length) {
      children.push(table([
        {key:'channel', label:'通道'}, {key:'point', label:'测点'},
      ], entry.confirmed, {caption:`${entry.station} 确认接线`}));
    } else if (entry.conflicts) {
      children.push(p(`所有候选偏移下均无可行配法，冲突通道：${entry.conflicts.channels.join('、')}。`, 'feedback'));
    } else {
      children.push(p('可行配法之间没有共有的接线，暂无可确认项。', 'subtle'));
    }
    children.push(p(`第 ${entry.version} 版 · 发布于 ${date(entry.published_at)}`, 'subtle'),
      link(`查看判定 #${entry.determination_id}`, `#swap/${entry.determination_id}`, {class:'quiet'}));
    return el('section', {class:'handover-station'}, h(3, entry.station), children);
  });
  return panel('通道接线确认', p('只确认所有可行配法共有的接线；数据更新后未发布的旧判定已作废。', 'subtle'), blocks);
}

export async function deliveryPage(route, refresh) {
  const {spec, runs} = workspace;
  const message = feedback();
  const artifacts = table([
    {label:'报告', render:row=>link(row.name,`#results/${row.id}`)},
    {label:'复核', render:row=>pill(REVIEW[row.review],row.review)},
    {label:'计算时间', render:row=>date(row.finished_at)},
    {label:'下载', render:row=>{
      const download = button('下载 CSV',{class:'quiet'});
      download.addEventListener('click', handler(download,message,() =>
        workspace.download(`/runs/${row.id}/export`,`${spec.short_name}-${row.id}.csv`)));
      return download;
    }},
  ], runs.filter(row=>row.status==='complete'), {caption:'可导出的结果', empty:'完成计算后会生成对应的报告。'});
  const delivery = spec.scheduled ? panel('站内分发回执', table([
    {key:'recipient',label:'收件团队'},
    {label:'回执',render:row=>pill(row.state==='delivered'?'已投递':'已拦截',row.state)},
    {key:'detail',label:'说明'}, {label:'时间',render:row=>date(row.created_at)},
    {label:'查看',render:row=>link(`运行 ${row.run_id}`,`#results/${row.run_id}`)},
  ],await workspace.deliveries(),{caption:'站内收件箱',empty:'计划到时执行，回执将在此更新。'})) : null;
  return el('div',{}, panel(spec.pages[6], p('按运行批次下载 CSV，复核状态随报告保留。','subtle'), artifacts, message),
    wiringPanel(await workspace.handover()),
    delivery, spec.scheduled && await runPage({...route,scheduling:true},refresh));
}
