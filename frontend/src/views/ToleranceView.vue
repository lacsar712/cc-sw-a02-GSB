<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { api } from '../api.js'

const role = ref(localStorage.getItem('role') || '')
const current = ref(null)
const changes = ref([])
const err = ref('')
const ok = ref('')
const newTol = ref(0.08)
const saving = ref(false)
let timer

async function refresh() {
  if (!localStorage.getItem('tok')) return
  try {
    const [cur, log] = await Promise.all([api('/api/tolerance'), api('/api/tolerance/changes')])
    current.value = cur
    changes.value = log
    err.value = ''
  } catch (e) {
    err.value = String(e.message || e)
  }
}

async function save() {
  err.value = ''
  ok.value = ''
  saving.value = true
  try {
    await api('/api/tolerance', {
      method: 'PUT',
      body: JSON.stringify({ tolerance_nm: Number(newTol.value) }),
    })
    ok.value = `已改档为 ${Number(newTol.value)} nm`
    await refresh()
  } catch (e) {
    err.value = String(e.message || e)
  } finally {
    saving.value = false
  }
}

function fmtTime(t) {
  return t ? new Date(t).toLocaleString() : '—'
}

onMounted(() => {
  role.value = localStorage.getItem('role') || ''
  refresh()
  timer = setInterval(refresh, 1000)
})
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <div>
    <h2>允差台</h2>
    <p v-if="err" style="color:#b00020">{{ err }}</p>
    <p v-if="ok" style="color:#1a7f37">{{ ok }}</p>

    <section style="margin:16px 0; padding:12px; border:1px solid #ccc;">
      <h3>现行档</h3>
      <p v-if="current" style="font-size:28px; font-weight:700; margin:8px 0;">
        {{ current.tolerance_nm }} nm
      </p>
      <p v-if="current" class="meta">
        最近改档：{{ current.updated_by }} 于 {{ fmtTime(current.updated_at) }}
      </p>
      <div v-if="role === 'writer'" style="margin-top:8px;">
        <label>
          新档 nm
          <input type="number" step="0.01" min="0.01" v-model.number="newTol" />
        </label>
        <button type="button" :disabled="saving" @click="save">改档</button>
      </div>
      <p v-else class="meta">巡检员只读，不可改档。</p>
    </section>

    <section style="margin:16px 0; padding:12px; border:1px solid #ccc;">
      <h3>改档流水</h3>
      <table border="1" cellpadding="6" style="border-collapse:collapse; width:100%;">
        <thead>
          <tr><th>时间</th><th>旧档</th><th>新档</th><th>操作人</th></tr>
        </thead>
        <tbody>
          <tr v-for="c in changes" :key="c.id">
            <td>{{ fmtTime(c.changed_at) }}</td>
            <td>{{ c.old_nm ?? '—' }}</td>
            <td>{{ c.new_nm }}</td>
            <td>{{ c.changed_by }}</td>
          </tr>
          <tr v-if="!changes.length"><td colspan="4">暂无改档记录</td></tr>
        </tbody>
      </table>
    </section>

    <section style="margin:16px 0; padding:12px; border:1px solid #ccc;">
      <h3>新档如何约束后续领取</h3>
      <ul>
        <li>改档只约束之后被领取的单：队列里尚未领走的新单，被领取时吃当时的现行档。</li>
        <li>已在领取中的单不受改档影响：领取那一刻会把当时的档位记在单上，判定继续吃记下的档。</li>
        <li>判定规则：|实测 − 标称| 不大于单上记的允差档写「合格」，否则写「超差」。</li>
      </ul>
    </section>
  </div>
</template>

<style scoped>
.meta {
  color: #666;
  font-size: 13px;
}
</style>
