<template>
  <section class="page" data-module="dispatch">
    <header class="page-head">
      <div>
        <h2>调度指令管理</h2>
        <p class="page-desc">维护调度指令单，围绕指令编号、下发单位、执行人、执行时限做组合检索、登记与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记调度指令单</button>
        <button class="btn" type="button" @click="exportRows">导出调度指令清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="search">
      <label v-for="field in filterFields" :key="field.key" class="filter-item">
        <span>{{ field.label }}</span>
        <input v-model="filters[field.key]" :placeholder="`按${field.label}检索`" />
      </label>
      <label class="filter-item">
        <span>指令状态</span>
        <select v-model="filters.status">
          <option value="">全部状态</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">
            <button
              v-if="column === '指令编号'"
              class="link"
              type="button"
              @click="openDetail(row)"
            >
              {{ row[column] ?? '—' }}
            </button>
            <template v-else>{{ row[column] ?? '—' }}</template>
          </td>
          <td class="row-actions">
            <template v-if="canOperate(row)">
              <button
                v-for="action in actions"
                :key="action"
                class="link"
                type="button"
                @click="runAction(action, row)"
              >
                {{ action }}
              </button>
            </template>
            <span v-else class="muted-text">跨单位指令仅可查看</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">{{ emptyText }}</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条调度指令记录</span>
      <span class="pager">
        <button class="btn ghost" type="button" :disabled="page <= 1" @click="turnPage(page - 1)">上一页</button>
        <span>第 {{ page }} / {{ pageCount }} 页</span>
        <button class="btn ghost" type="button" :disabled="page >= pageCount" @click="turnPage(page + 1)">下一页</button>
      </span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
      <span v-else-if="noticeMessage" class="notice-text">{{ noticeMessage }}</span>
    </footer>

    <div v-if="detail" class="overlay" @click.self="closeDetail">
      <div class="dialog">
        <h3>调度指令单详情</h3>
        <dl class="detail-grid">
          <template v-for="column in columns" :key="column">
            <dt>{{ column }}</dt>
            <dd>{{ detail[column] ?? '—' }}</dd>
          </template>
        </dl>
        <div class="dialog-actions">
          <button class="btn" type="button" @click="closeDetail">关闭</button>
        </div>
      </div>
    </div>

    <div v-if="showCreate" class="overlay" @click.self="closeCreate">
      <form class="dialog" @submit.prevent="submitCreate">
        <h3>登记调度指令单</h3>
        <label v-for="field in createFields" :key="field.key" class="form-item">
          <span>{{ field.label }}<em v-if="field.required"> *</em></span>
          <input v-model="createForm[field.key]" :type="field.type ?? 'text'" />
        </label>
        <p v-if="createError" class="error-text">{{ createError }}</p>
        <div class="dialog-actions">
          <button class="btn primary" type="submit">提交</button>
          <button class="btn ghost" type="button" @click="closeCreate">取消</button>
        </div>
      </form>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { request } from '@/api/client'
import { useSessionStore } from '@/stores/session'

type Row = Record<string, string | number | boolean | null>

const ENDPOINT = '/api/dispatch'
const columns = ["指令编号", "下发单位", "指令类型", "下发时间", "执行时限", "执行人", "执行结果", "指令状态"]
const actions = ["确认执行", "完成回复", "驳回指令"]
const statuses = ["待执行", "执行中", "已执行", "已驳回"]
const filterFields = [
  { key: 'keyword', label: '指令编号' },
  { key: 'unit', label: '下发单位' },
  { key: 'executor', label: '执行人' },
  { key: 'deadline', label: '执行时限' },
]
const createFields = [
  { key: '指令编号', label: '指令编号', required: true },
  { key: '下发单位', label: '下发单位', required: true },
  { key: '指令类型', label: '指令类型', required: true },
  { key: '下发时间', label: '下发时间', type: 'date' },
  { key: '执行时限', label: '执行时限', type: 'date' },
  { key: '执行人', label: '执行人' },
]
const PAGE_SIZE = 20

const session = useSessionStore()
const route = useRoute()
const router = useRouter()

const rows = ref<Row[]>([])
const total = ref(0)
const page = ref(1)
const errorMessage = ref('')
const noticeMessage = ref('')
const filters = ref<Record<string, string>>({ keyword: '', unit: '', executor: '', deadline: '', status: '' })
const stats = ref([
  { label: '待执行指令', value: 0 },
  { label: '执行中指令', value: 0 },
  { label: '已执行指令', value: 0 },
  { label: '已驳回指令', value: 0 },
])
const detail = ref<Row | null>(null)
const showCreate = ref(false)
const createForm = ref<Record<string, string>>({})
const createError = ref('')

const pageCount = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)))
const hasFilters = computed(() => Object.values(filters.value).some((value) => String(value ?? '').trim() !== ''))
const emptyText = computed(() => (hasFilters.value
  ? '未查到符合条件的调度指令，请调整检索条件后重试'
  : '暂无调度指令数据，可先登记调度指令单'))

function canOperate(row: Row) {
  return String(row['下发单位'] ?? '') === session.unit
}

function filterParams() {
  const params = new URLSearchParams()
  for (const field of filterFields) {
    const value = String(filters.value[field.key] ?? '').trim()
    if (value) params.set(field.key, value)
  }
  const status = String(filters.value.status ?? '').trim()
  if (status) params.set('status', status)
  return params
}

function queryParams() {
  const params = filterParams()
  params.set('page', String(page.value))
  params.set('size', String(PAGE_SIZE))
  return params
}

function syncRoute() {
  // 条件与页码写回地址栏：翻页、进出详情再返回，检索口径都不丢
  const query: Record<string, string> = {}
  filterParams().forEach((value, key) => { query[key] = value })
  if (page.value > 1) query.page = String(page.value)
  void router.replace({ query })
}

function restoreFromRoute() {
  const query = route.query
  for (const field of filterFields) {
    const value = query[field.key]
    if (typeof value === 'string') filters.value[field.key] = value
  }
  if (typeof query.status === 'string') filters.value.status = query.status
  const routePage = Number(query.page)
  if (Number.isInteger(routePage) && routePage > 0) page.value = routePage
}

function search() {
  page.value = 1
  void reload()
}

function resetFilters() {
  filters.value = { keyword: '', unit: '', executor: '', deadline: '', status: '' }
  page.value = 1
  void reload()
}

function turnPage(target: number) {
  if (target < 1 || target > pageCount.value) return
  page.value = target
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export?${filterParams().toString()}`, '_blank')
}

function openCreate() {
  createForm.value = { 指令编号: '', 下发单位: session.unit, 指令类型: '', 下发时间: '', 执行时限: '', 执行人: '' }
  createError.value = ''
  showCreate.value = true
}

function closeCreate() {
  showCreate.value = false
}

async function submitCreate() {
  createError.value = ''
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: createForm.value }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      createError.value = payload.message ?? '调度指令单登记失败'
      return
    }
    showCreate.value = false
    noticeMessage.value = payload.message ?? '调度指令单已登记'
    await reload()
  } catch (error) {
    createError.value = error instanceof Error ? error.message : '调度指令单登记失败'
  }
}

async function openDetail(row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) {
      throw new Error('调度指令单详情读取失败')
    }
    detail.value = await response.json()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '调度指令单详情读取失败'
  }
}

function closeDetail() {
  detail.value = null
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({
        values: { action, 操作人: session.operator, 操作单位: session.unit },
      }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message ?? '调度指令动作未生效，请稍后重试')
    }
    noticeMessage.value = payload.message ?? `调度指令单已${action}`
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '调度指令操作失败'
  }
}

async function loadStats() {
  try {
    const response = await request(`${ENDPOINT}/stats`)
    if (!response.ok) return
    const payload = await response.json()
    stats.value = [
      { label: '待执行指令', value: payload['待执行'] ?? 0 },
      { label: '执行中指令', value: payload['执行中'] ?? 0 },
      { label: '已执行指令', value: payload['已执行'] ?? 0 },
      { label: '已驳回指令', value: payload['已驳回'] ?? 0 },
    ]
  } catch {
    // 统计卡片读取失败不阻塞列表
  }
}

async function reload() {
  errorMessage.value = ''
  noticeMessage.value = ''
  syncRoute()
  try {
    const response = await request(`${ENDPOINT}?${queryParams().toString()}`)
    if (!response.ok) {
      throw new Error('调度指令单列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? 0
  } catch (error) {
    // 读取失败时清空列表，不拿上一次结果顶替
    rows.value = []
    total.value = 0
    errorMessage.value = error instanceof Error ? error.message : '调度指令列表读取失败'
  }
  void loadStats()
}

onMounted(() => {
  restoreFromRoute()
  void reload()
})
</script>
