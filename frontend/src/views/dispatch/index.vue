<template>
  <section class="page" data-module="dispatch">
    <header class="page-head">
      <div>
        <h2>调度指令管理</h2>
        <p class="page-desc">
          按执行时限、下发单位、执行人组合检索（含已执行归档指令）；当前值班：{{ session.operator }}（{{ session.unit }}），跨单位指令仅可查看。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记调度指令</button>
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
      <label class="filter-item">
        <span>执行时限</span>
        <input v-model="filters.deadline" placeholder="如 2026-09 或 2026-09-20" />
      </label>
      <label class="filter-item">
        <span>下发单位</span>
        <input v-model="filters.unit" placeholder="按下发单位检索" />
      </label>
      <label class="filter-item">
        <span>执行人</span>
        <input v-model="filters.operator" placeholder="按执行人检索" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">
            <span v-if="column === '指令状态'" class="status-tag" :class="`tag-${statusKey(row[column])}`">{{ row[column] }}</span>
            <span v-else>{{ row[column] || '—' }}</span>
          </td>
          <td class="row-actions">
            <button class="link" type="button" @click="openDetail(row)">查看详情</button>
            <template v-if="canModify(row)">
              <button
                v-if="row['指令状态'] === '执行中' && !String(row['执行结果'] ?? '')"
                class="link"
                type="button"
                @click="openSubmit(row)"
              >
                提交执行结果
              </button>
              <button
                v-else
                class="link"
                type="button"
                @click="execute(row)"
              >
                {{ executeLabel(row) }}
              </button>
            </template>
            <span v-else class="readonly-hint">跨单位只读</span>
          </td>
        </tr>
        <tr v-if="loaded && !rows.length && !errorMessage">
          <td :colspan="columns.length + 1" class="empty-state">
            没有符合当前检索条件的调度指令（含已执行归档），可调整执行时限、下发单位或执行人后重新查询
          </td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条调度指令记录</span>
      <div class="pager">
        <button class="btn" type="button" :disabled="page <= 1" @click="goPage(page - 1)">上一页</button>
        <span>第 {{ page }} / {{ totalPages }} 页（每页 {{ size }} 条，筛选条件保留）</span>
        <button class="btn" type="button" :disabled="page >= totalPages" @click="goPage(page + 1)">下一页</button>
      </div>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <!-- 单条详情：字段与列表取同一接口同一序列化，执行结果两处必然一致 -->
    <div v-if="detail" class="modal-mask" @click.self="detail = null">
      <div class="modal">
        <h3>调度指令详情 · {{ detail['指令编号'] }}</h3>
        <dl class="detail-grid">
          <template v-for="column in columns" :key="column">
            <dt>{{ column }}</dt>
            <dd>{{ detail[column] || '—' }}</dd>
          </template>
          <dt>所属单位可操作</dt>
          <dd>{{ canModify(detail) ? '是（本单位）' : '否（跨单位，仅查看）' }}</dd>
          <template v-if="detailTodo">
            <dt>待办执行时限</dt>
            <dd>{{ detailTodo['执行时限'] || '—' }}</dd>
            <dt>结果提交人 / 时间</dt>
            <dd>{{ detailTodo['提交人'] || '—' }}<template v-if="detailTodo['提交时间']"> · {{ detailTodo['提交时间'] }}</template></dd>
          </template>
        </dl>
        <div class="modal-foot">
          <button class="btn" type="button" @click="detail = null">关闭</button>
        </div>
      </div>
    </div>

    <!-- 执行结果提交：同一指令只收第一条，重复提交由后端原样拒收 -->
    <div v-if="submitTarget" class="modal-mask" @click.self="closeSubmit">
      <div class="modal">
        <h3>提交执行结果 · {{ submitTarget['指令编号'] }}</h3>
        <p class="modal-tip">指令 {{ submitTarget['指令编号'] }}（{{ submitTarget['下发单位'] }}）处于执行中，结果提交后落库并流转为「已执行」。</p>
        <textarea v-model="submitText" rows="4" placeholder="请填写执行结果，提交后不可覆盖"></textarea>
        <div class="modal-foot">
          <button class="btn" type="button" @click="closeSubmit">取消</button>
          <button class="btn primary" type="button" :disabled="submitting" @click="confirmSubmit">提交结果</button>
        </div>
      </div>
    </div>

    <!-- 登记新指令 -->
    <div v-if="creating" class="modal-mask" @click.self="creating = false">
      <div class="modal">
        <h3>登记调度指令</h3>
        <dl class="detail-grid form-grid">
          <template v-for="field in createFields" :key="field">
            <dt>{{ field }}</dt>
            <dd><input v-model="createForm[field]" :placeholder="`请输入${field}`" /></dd>
          </template>
        </dl>
        <div class="modal-foot">
          <button class="btn" type="button" @click="creating = false">取消</button>
          <button class="btn primary" type="button" @click="confirmCreate">登记</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'
import { useSessionStore } from '@/stores/session'

type Todo = Record<string, string>
type Row = Record<string, string | number | boolean | null | Todo>
type Filters = { deadline: string; unit: string; operator: string }

const ENDPOINT = '/api/dispatch'
const session = useSessionStore()

const columns = ['指令编号', '下发单位', '指令类型', '下发时间', '执行时限', '执行人', '执行结果', '指令状态'] as const
const statusKey = (value: unknown) => ({
  待执行: 'pending',
  执行中: 'running',
  已执行: 'done',
} as Record<string, string>)[String(value)] || 'pending'

const rows = ref<Row[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(10)
const loaded = ref(false)
const errorMessage = ref('')
const filters = reactive<Filters>({ deadline: '', unit: '', operator: '' })

const stats = ref([
  { label: '待执行指令', value: 0 },
  { label: '执行中指令', value: 0 },
  { label: '已执行（归档）', value: 0 },
])

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / size.value)))
const canModify = (row: Row) => String(row['下发单位'] ?? '') === session.unit
const executeLabel = (row: Row) => {
  if (row['指令状态'] === '已执行') return '执行（退回）'
  if (row['指令状态'] === '执行中' && String(row['执行结果'] ?? '')) return '执行（恢复已执行）'
  return '执行'
}
function todoOf(row: Row | null): Todo | null {
  const todo = row ? row['待办'] : null
  return todo && typeof todo === 'object' ? (todo as Todo) : null
}
const detailTodo = computed(() => todoOf(detail.value))

function filterParams() {
  const params = new URLSearchParams()
  if (filters.deadline.trim()) params.set('deadline', filters.deadline.trim())
  if (filters.unit.trim()) params.set('unit', filters.unit.trim())
  if (filters.operator.trim()) params.set('operator', filters.operator.trim())
  return params
}

function buildQuery(targetPage: number) {
  const params = filterParams()
  params.set('page', String(targetPage))
  params.set('size', String(size.value))
  return params.toString()
}

async function reload(targetPage = page.value) {
  errorMessage.value = ''
  rows.value = [] // 先清旧数据，绝不用上一次结果顶替本次查询
  loaded.value = false
  try {
    const response = await request(`${ENDPOINT}?${buildQuery(targetPage)}`)
    if (!response.ok) throw new Error('调度指令列表读取失败')
    const payload = await response.json()
    page.value = targetPage
    rows.value = payload.items ?? []
    total.value = payload.total ?? 0
  } catch (error) {
    total.value = 0
    errorMessage.value = error instanceof Error ? error.message : '调度指令列表读取失败'
  } finally {
    loaded.value = true
  }
}

function search() {
  void reload(1) // 新查询回到第一页，条件随分页继续保留
}

function goPage(target: number) {
  if (target < 1 || target > totalPages.value) return
  void reload(target)
}

function resetFilters() {
  filters.deadline = ''
  filters.unit = ''
  filters.operator = ''
  void reload(1)
}

async function loadStats() {
  try {
    const response = await request(`${ENDPOINT}/stats`)
    if (!response.ok) return
    const data = await response.json()
    stats.value = [
      { label: '待执行指令', value: Number(data['待执行'] ?? 0) },
      { label: '执行中指令', value: Number(data['执行中'] ?? 0) },
      { label: '已执行（归档）', value: Number(data['已执行'] ?? 0) },
    ]
  } catch {
    // 统计卡不阻塞主列表
  }
}

// 导出与列表同口径同条件，条数即筛选后的 total
function exportRows() {
  const query = filterParams().toString()
  window.open(`${ENDPOINT}/export${query ? `?${query}` : ''}`, '_blank')
}

// ---------------- 单条详情 ----------------
const detail = ref<Row | null>(null)

async function openDetail(row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (response.status === 404) throw new Error('该调度指令不存在或已归档')
    if (!response.ok) throw new Error('调度指令详情读取失败')
    detail.value = (await response.json()) as Row
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '调度指令详情读取失败'
  }
}

// ---------------- 执行 / 退回 ----------------
async function execute(row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/execute`, {
      method: 'POST',
      body: JSON.stringify({ values: { operator: session.operator, unit: session.unit } }),
    })
    const payload = await response.json()
    if (!payload.ok) throw new Error(payload.message || '操作未生效')
    errorMessage.value = payload.message
    await Promise.all([reload(), loadStats()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '操作未生效'
  }
}

// ---------------- 提交执行结果 ----------------
const submitTarget = ref<Row | null>(null)
const submitText = ref('')
const submitting = ref(false)

function openSubmit(row: Row) {
  submitTarget.value = row
  submitText.value = ''
}

function closeSubmit() {
  submitTarget.value = null
  submitText.value = ''
}

async function confirmSubmit() {
  if (!submitTarget.value) return
  submitting.value = true
  try {
    const response = await request(`${ENDPOINT}/${submitTarget.value.id}/result`, {
      method: 'POST',
      body: JSON.stringify({ values: { result: submitText.value, operator: session.operator, unit: session.unit } }),
    })
    const payload = await response.json()
    if (!payload.ok) throw new Error(payload.message || '执行结果提交失败')
    closeSubmit()
    errorMessage.value = payload.message
    await Promise.all([reload(), loadStats()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '执行结果提交失败'
  } finally {
    submitting.value = false
  }
}

// ---------------- 登记 ----------------
const creating = ref(false)
const createFields = ['指令编号', '下发单位', '指令类型', '下发时间', '执行时限', '执行人'] as const
const createForm = reactive<Record<string, string>>(Object.fromEntries(createFields.map((f) => [f, ''])))

function openCreate() {
  createFields.forEach((f) => { createForm[f] = '' })
  creating.value = true
}

async function confirmCreate() {
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: { ...createForm } }),
    })
    const payload = await response.json()
    if (!payload.ok) throw new Error(payload.message || '调度指令登记失败')
    creating.value = false
    errorMessage.value = payload.message
    await Promise.all([reload(1), loadStats()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '调度指令登记失败'
  }
}

onMounted(() => {
  void reload(1)
  void loadStats()
})
</script>

<style scoped>
.pager { display: flex; align-items: center; gap: 8px; }
.pager .btn:disabled { opacity: 0.5; cursor: not-allowed; }
.status-tag { display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 12px; }
.tag-pending { background: #fef3c7; color: #92400e; }
.tag-running { background: #dbeafe; color: #1e40af; }
.tag-done { background: #dcfce7; color: #166534; }
.readonly-hint { color: var(--muted); font-size: 12px; }
.modal-mask {
  position: fixed; inset: 0; background: rgba(15, 23, 42, 0.45);
  display: flex; align-items: center; justify-content: center; z-index: 20;
}
.modal {
  width: 560px; max-width: 92vw; max-height: 86vh; overflow: auto;
  background: #fff; border-radius: 10px; padding: 18px 20px;
}
.modal h3 { margin: 0 0 12px; font-size: 16px; }
.modal-tip { color: var(--muted); font-size: 13px; margin: 0 0 10px; }
.modal textarea, .modal input {
  width: 100%; border: 1px solid var(--border); border-radius: 6px; padding: 6px 8px; font: inherit;
}
.modal-foot { display: flex; justify-content: flex-end; gap: 8px; margin-top: 14px; }
.detail-grid { display: grid; grid-template-columns: 130px 1fr; gap: 6px 12px; margin: 0; font-size: 13px; }
.detail-grid dt { color: var(--muted); }
.detail-grid dd { margin: 0; }
.form-grid dd { margin: 0 0 6px; }
</style>
