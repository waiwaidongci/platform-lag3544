import {request, saveFile} from '../api/http.js';
import {session} from './session.js';

const call = (path, body) => request(path, {token:session.token, body});
export const workspace = {
  spec: null,
  datasets: [],
  runs: [],
  async init() { this.spec = await request('/spec'); },
  async refresh() { [this.datasets, this.runs] = await Promise.all([call('/datasets'), call('/runs')]); },
  getDataset: (id, offset = 0) => call(`/datasets/${id}?offset=${offset}`),
  getRun: id => call(`/runs/${id}`),
  upload: data => call('/datasets', data),
  start: data => call('/runs', data),
  review: (id, data) => call(`/runs/${id}/review`, data),
  audit: () => call('/audit'),
  schedules: () => call('/schedules'),
  deliveries: () => call('/deliveries'),
  schedule: data => call('/schedules', data),
  disable: id => call(`/schedules/${id}/disable`, {}),
  download: (path, filename) => saveFile(path, session.token, filename),
  swapBatches: () => call('/swap/batches'),
  swapBatch: (id, offset = 0) => call(`/swap/batches/${id}?offset=${offset}`),
  uploadCalibration: data => call('/swap/batches', data),
  tonePeriods: station => call(`/swap/tone-periods${station ? `?station=${encodeURIComponent(station)}` : ''}`),
  addTonePeriod: data => call('/swap/tone-periods', data),
  removeTonePeriod: id => call(`/swap/tone-periods/${id}/delete`, {}),
  determinations: station => call(`/swap/determinations${station ? `?station=${encodeURIComponent(station)}` : ''}`),
  determination: id => call(`/swap/determinations/${id}`),
  determine: data => call('/swap/determinations', data),
  publishDetermination: id => call(`/swap/determinations/${id}/publish`, {}),
  handover: () => call('/swap/handover'),
};
