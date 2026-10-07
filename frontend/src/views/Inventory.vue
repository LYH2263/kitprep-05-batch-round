<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
const rows = ref<any[]>([])
const drafts = ref<Record<number, string>>({})
const msg = ref('')
const err = ref('')
function fillDrafts() {
  rows.value.forEach(r => { drafts.value[r.id] = r.prep_multiple ?? '' })
}
async function load() {
  rows.value = await api('/inventory')
  fillDrafts()
}
async function save(r: any) {
  msg.value = ''; err.value = ''
  const raw = String(drafts.value[r.id] ?? '').trim()
  const v = raw === '' ? null : Number(raw)
  if (v !== null && (!Number.isFinite(v) || v <= 0)) {
    err.value = `${r.name}:起备倍数必须为正数(留空表示不取整),栏、单、缺料贴均保持写入前状态`
    drafts.value[r.id] = r.prep_multiple ?? ''  // 栏位退回写入前
    return
  }
  try {
    const res = await api(`/inventory/${r.id}/multiple`, {
      method: 'PUT',
      body: JSON.stringify({ prep_multiple: v }),
    })
    msg.value = `${r.name} 倍数已保存为 ${res.prep_multiple ?? '未配置'},在用备料单已整张按新倍数取整重写(单号 ${res.rewritten_runs.join(', ') || '无'})`
    await load()
  } catch (e: any) {
    err.value = `${r.name} 保存失败:${e.message}`
    await load()  // 栏位退回写入前
  }
}
onMounted(load)
</script>
<template>
  <h1>库存</h1>
  <p class="sub">中央厨房原料库存 · 起备倍数:需求按倍数的整数倍四舍五入后占用,留空不取整</p>
  <p v-if="msg" class="badge badge-ok">{{ msg }}</p>
  <p v-if="err" class="badge badge-bad">{{ err }}</p>
  <div class="card">
    <table>
      <thead><tr><th>编码</th><th>名称</th><th>结存</th><th>单位</th><th>起备倍数</th><th></th></tr></thead>
      <tbody>
        <tr v-for="r in rows" :key="r.id ?? JSON.stringify(r)">
          <td>{{ r.code }}</td><td>{{ r.name }}</td><td>{{ r.stock_qty }}</td><td>{{ r.unit }}</td>
          <td>
            <input
              v-model="drafts[r.id]"
              class="kp-multiple-input"
              type="text"
              inputmode="decimal"
              placeholder="未配置"
              @keyup.enter="save(r)"
            />
          </td>
          <td><button class="btn" @click="save(r)">保存倍数</button></td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
<style scoped>
.kp-multiple-input {
  width: 6.5rem; padding: 0.25rem 0.4rem;
  border: 1px solid var(--kp-steel); border-radius: 2px;
  background: #fffdf8; color: var(--kp-ink); font-size: 0.85rem;
}
p.badge { display: block; padding: 0.45rem 0.6rem; margin: 0 0 0.6rem; }
</style>
