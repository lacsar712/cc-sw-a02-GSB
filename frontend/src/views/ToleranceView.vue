<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api } from '../api.js'

const role = ref(localStorage.getItem('role') || '')
const current = ref(null)
const history = ref([])
const err = ref('')
const notice = ref('')
const newTier = ref(0.08)
let timer

const isWriter = computed(() => role.value === 'writer')

async function refresh() {
  if (!localStorage.getItem('tok')) return
  try {
    const data = await api('/api/tolerance')
    current.value = data.current
    history.value = data.history
    err.value = ''
  } catch (e) {
    err.value = String(e.message || e)
  }
}

async function changeTier() {
  err.value = ''
  notice.value = ''
  try {
    await api('/api/tolerance', {
      method: 'POST',
      body: JSON.stringify({ tolerance_nm: newTier.value }),
    })
    notice.value = `已改档为 ${newTier.value} nm`
    await refresh()
  } catch (e) {
    err.value = String(e.message || e)
  }
}

function fmtTime(t) {
  return t ? String(t).replace('T', ' ').slice(0, 19) : ''
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
    <p v-if="err" style="color:#b00020">{{ err }}</p>
    <p v-if="notice" style="color:#1a7f37">{{ notice }}</p>

    <section style="margin:16px 0; padding:12px; border:1px solid #ccc;">
      <h3>现行档</h3>
      <p v-if="current" style="font-size:20px; font-weight:700; margin:8px 0;">
        {{ current.tolerance_nm }} nm
      </p>
      <p v-if="current" style="color:#666; font-size:13px;">
        由 {{ current.changed_by }} 于 {{ fmtTime(current.changed_at) }} 设定
      </p>
      <p v-else>暂无档位记录</p>
      <div v-if="isWriter" style="margin-top:8px;">
        <label>新档位 nm <input type="number" step="0.01" min="0.0001" v-model.number="newTier" /></label>
        <button type="button" @click="changeTier">改档</button>
      </div>
      <p v-else style="color:#666; font-size:13px;">巡检员只读，不可改档。</p>
    </section>

    <section style="margin:16px 0; padding:12px; border:1px solid #ccc;">
      <h3>改档流水</h3>
      <table border="1" cellpadding="6" style="border-collapse:collapse; width:100%;">
        <thead>
          <tr><th>序号</th><th>档位 nm</th><th>改档人</th><th>改档时间</th></tr>
        </thead>
        <tbody>
          <tr v-for="t in history" :key="t.id">
            <td>{{ t.id }}</td>
            <td>{{ t.tolerance_nm }}</td>
            <td>{{ t.changed_by }}</td>
            <td>{{ fmtTime(t.changed_at) }}</td>
          </tr>
          <tr v-if="!history.length"><td colspan="4">暂无流水</td></tr>
        </tbody>
      </table>
    </section>

    <section style="margin:16px 0; padding:12px; border:1px solid #ccc;">
      <h3>新档如何约束后续领取</h3>
      <ul style="margin:8px 0; padding-left:20px; line-height:1.8;">
        <li>改档生效后，仍未被领走的待处理单一律按新档判定。</li>
        <li>已在领取中的单继续按领走那一刻记下的档判定，结论不回溯。</li>
        <li>判定规则：|实测 − 标称| 不大于现行档写「合格」，否则写「超差」。</li>
      </ul>
    </section>
  </div>
</template>
