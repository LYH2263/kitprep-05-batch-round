<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
const rows = ref<any[]>([])
const drafts = ref<Record<number, string>>({})
const saving = ref<number | null>(null)
const error = ref('')
const notice = ref('')

onMounted(load)

async function load() {
  rows.value = await api('/inventory')
  for (const r of rows.value) drafts.value[r.id] = r.prep_multiple == null ? '' : String(r.prep_multiple)
}

function draftFor(r: any) { return drafts.value[r.id] ?? '' }

async function save(r: any) {
  error.value = ''; notice.value = ''
  const text = (drafts.value[r.id] ?? '').trim()
  let payload: any
  if (text === '') {
    payload = { prep_multiple: null }
  } else {
    const v = Number(text)
    // 0、负数、非数字：前端直接拦住，不发请求；栏位恢复到保存前。
    if (!Number.isFinite(v) || v <= 0) {
      error.value = `「${r.name}」倍数必须是正数；0、负数或非数字不会写入，已停在写入前。`
      drafts.value[r.id] = r.prep_multiple == null ? '' : String(r.prep_multiple)
      return
    }
    payload = { prep_multiple: v }
  }
  saving.value = r.id
  try {
    const res = await api(`/inventory/${r.id}/multiple`, { method: 'PUT', body: JSON.stringify(payload) })
    r.prep_multiple = res.prep_multiple
    drafts.value[r.id] = res.prep_multiple == null ? '' : String(res.prep_multiple)
    const n = res.rewritten_runs?.length ?? 0
    notice.value = `「${r.name}」倍数已保存（${res.prep_multiple == null ? '未配倍数，不取整' : '按 ' + res.prep_multiple + ' 向上取整'}），${n > 0 ? `已整张重写 ${n} 张正在用的备料单` : '暂无在用备料单'}`
  } catch (e: any) {
    // 栏、单、缺料贴全部停在写入前：本地栏位一并退回。
    drafts.value[r.id] = r.prep_multiple == null ? '' : String(r.prep_multiple)
    error.value = `保存失败，已全部退回写入前：${e.message || e}`
  } finally {
    saving.value = null
  }
}
</script>
<template>
  <h1>库存</h1>
  <p class="sub">中央厨房原料库存 · 起备倍数（保存倍数只改倍数栏，并整张重写正在用的备料单；历史单不动）</p>
  <p v-if="notice" class="badge badge-ok" style="font-size:0.78rem;padding:0.3rem 0.6rem">{{ notice }}</p>
  <p v-if="error" class="badge badge-bad" style="font-size:0.78rem;padding:0.3rem 0.6rem">{{ error }}</p>
  <div class="card">
    <table>
      <thead><tr><th>编码</th><th>名称</th><th>结存</th><th>单位</th><th>起备倍数</th><th></th></tr></thead>
      <tbody>
        <tr v-for="r in rows" :key="r.id">
          <td>{{ r.code }}</td><td>{{ r.name }}</td><td>{{ r.stock_qty }}</td><td>{{ r.unit }}</td>
          <td>
            <input v-model="drafts[r.id]" inputmode="decimal" placeholder="未配·不取整"
              style="width:7rem;padding:0.25rem 0.4rem" :disabled="saving === r.id" />
          </td>
          <td>
            <button class="btn" style="padding:0.25rem 0.7rem;font-size:0.78rem"
              :disabled="saving === r.id || draftFor(r).trim() === (r.prep_multiple == null ? '' : String(r.prep_multiple))"
              @click="save(r)">保存倍数</button>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
