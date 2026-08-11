<template>
  <section class="autonomics-page" aria-labelledby="autonomics-title">
    <header class="page-header">
      <div><p class="kicker">AUTONOMOUS RUNTIME</p><h3 id="autonomics-title">{{ t('持续执行与调度', 'Continuous execution & scheduling') }}</h3><p>{{ t('查看工作器健康、定时运行、目标迭代与预算边界。', 'Inspect worker health, scheduled runs, goal iterations, and budget boundaries.') }}</p></div>
      <button type="button" :disabled="loading" @click="loadAll">{{ t('刷新', 'Refresh') }}</button>
    </header>

    <section class="health-strip" :class="healthReady ? 'ready' : 'degraded'" aria-live="polite">
      <div><span class="health-mark" /><strong>{{ healthReady ? t('运行时就绪', 'Runtime ready') : t('运行时需关注', 'Runtime needs attention') }}</strong><small>{{ workerSummary }}</small></div>
      <code>{{ health.running === true ? 'RUNNING' : 'STOPPED' }}</code>
    </section>

    <div class="mode-tabs" role="tablist" :aria-label="t('自治运行区域', 'Autonomous runtime sections')">
      <button v-for="tab in tabs" :id="`autonomics-tab-${tab.id}`" :key="tab.id" role="tab" :aria-selected="active === tab.id" @click="active = tab.id">{{ t(tab.zh, tab.en) }}</button>
    </div>

    <OperationalAccessPrompt v-if="needsAccess" @connected="accessConnected" />
    <div v-else-if="loading" class="skeleton-grid"><i v-for="item in 5" :key="item" /></div>
    <div v-else-if="error" class="error-panel" role="alert"><strong>{{ t('自治运行数据不可用', 'Autonomous runtime data unavailable') }}</strong><span>{{ error }}</span><button type="button" @click="loadAll">{{ t('重试', 'Retry') }}</button></div>

    <template v-else>
      <section v-if="active === 'overview'" class="overview-grid" role="tabpanel" aria-labelledby="autonomics-tab-overview">
        <article class="metric-block"><span>{{ t('活动定时任务', 'Active jobs') }}</span><strong>{{ activeJobs }}</strong><small>{{ t('共', 'of') }} {{ jobs.length }}</small></article>
        <article class="metric-block wide"><span>{{ t('最近运行', 'Recent runs') }}</span><strong>{{ runs.length ? status(runs[0].state).label : '—' }}</strong><small>{{ runs.length ? formatDate(runs[0].updated_at) : t('尚无执行记录', 'No execution history') }}</small></article>
        <article class="metric-block"><span>{{ t('持续目标', 'Continuous goals') }}</span><strong>{{ activeGoals }}</strong><small>{{ t('共', 'of') }} {{ goals.length }}</small></article>
        <div class="worker-list"><h4>{{ t('工作器', 'Workers') }}</h4><div v-if="workers.length === 0" class="empty">{{ t('没有工作器快照', 'No worker snapshot') }}</div><div v-for="worker in workers" :key="worker.name" class="worker-row"><span class="health-mark" :class="worker.ready ? '' : 'off'" /><div><strong>{{ worker.name }}</strong><small>{{ worker.detail }}</small></div></div></div>
      </section>

      <section v-if="active === 'scheduler'" class="split-layout" role="tabpanel" aria-labelledby="autonomics-tab-scheduler">
        <form class="editor" @submit.prevent="createJob"><h4>{{ t('新建定时任务', 'New scheduled job') }}</h4><label><span>{{ t('任务标识', 'Job ID') }}</span><input v-model.trim="jobDraft.job_id" required maxlength="128" /></label><div class="field-pair"><label><span>Cron</span><input v-model.trim="jobDraft.schedule" required /></label><label><span>{{ t('时区', 'Timezone') }}</span><input v-model.trim="jobDraft.timezone" required /></label></div><label><span>{{ t('执行提示词', 'Execution prompt') }}</span><textarea v-model="jobDraft.prompt" required /></label><label><span>{{ t('失败重试上限', 'Maximum retries') }}</span><input v-model.number="jobDraft.max_retries" type="number" min="0" max="100" /></label><button class="primary" type="submit" :disabled="busy.createJob">{{ busy.createJob ? t('创建中…', 'Creating…') : t('创建任务', 'Create job') }}</button></form>
        <div class="resource-list"><div v-if="jobs.length === 0" class="empty"><strong>{{ t('没有定时任务', 'No scheduled jobs') }}</strong><span>{{ t('创建后，扫描器会按持久化游标触发执行。', 'Once created, the scanner fires from a durable cursor.') }}</span></div><article v-for="job in jobs" :key="String(job.job_id)" class="resource-row"><div><span class="status" :class="status(job.status).tone">{{ status(job.status).label }}</span><strong>{{ job.job_id }}</strong><p><code>{{ job.schedule }}</code> · {{ job.timezone }} · {{ formatDate(job.next_run_at) }}</p></div><div class="actions"><button type="button" :disabled="isBusy(String(job.job_id))" @click="toggleJob(job)">{{ job.status === 'active' ? t('暂停', 'Pause') : t('恢复', 'Resume') }}</button><button type="button" :disabled="isBusy(String(job.job_id))" @click="triggerJob(String(job.job_id))">{{ t('立即运行', 'Run now') }}</button></div></article><button v-if="jobCursor" class="load-more" type="button" :disabled="busy.moreJobs" @click="moreJobs">{{ t('加载更多', 'Load more') }}</button></div>
        <div class="runs-panel"><div class="section-heading"><h4>{{ t('运行历史', 'Run history') }}</h4><span>{{ runs.length }}</span></div><div v-if="runs.length === 0" class="empty compact">{{ t('暂无运行记录。', 'No runs recorded.') }}</div><article v-for="run in runViews" :key="run.id" class="run-row"><span class="status" :class="run.status.tone">{{ run.status.label }}</span><div><strong>{{ run.id }}</strong><small>{{ run.jobId }} · {{ t('第', 'attempt') }} {{ run.attemptNumber }} {{ t('次尝试', '') }}</small></div><time>{{ formatDate(runs.find(item => item.run_id === run.id)?.updated_at) }}</time></article><button v-if="runCursor" class="load-more" type="button" :disabled="busy.moreRuns" @click="moreRuns">{{ t('加载更多', 'Load more') }}</button></div>
      </section>

      <section v-if="active === 'goals'" class="goals-layout" role="tabpanel" aria-labelledby="autonomics-tab-goals">
        <form class="editor goal-editor" @submit.prevent="createGoal"><h4>{{ t('启动持续目标', 'Start a continuous goal') }}</h4><label><span>{{ t('会话标识', 'Session ID') }}</span><input v-model.trim="goalDraft.session_id" required /></label><label><span>{{ t('目标', 'Goal') }}</span><textarea v-model="goalDraft.goal_text" required /></label><label><span>{{ t('验收标准（每行一条）', 'Acceptance criteria (one per line)') }}</span><textarea v-model="goalDraft.criteria" required /></label><div class="budget-inputs"><label><span>{{ t('迭代', 'Iterations') }}</span><input v-model.number="goalDraft.max_iterations" type="number" min="1" /></label><label><span>Tokens</span><input v-model.number="goalDraft.max_tokens" type="number" min="1" /></label><label><span>{{ t('成本 USD', 'Cost USD') }}</span><input v-model.number="goalDraft.max_estimated_cost" type="number" min="0.01" step="0.01" /></label><label><span>{{ t('活动秒数', 'Active seconds') }}</span><input v-model.number="goalDraft.max_active_seconds" type="number" min="1" /></label></div><button class="primary" type="submit" :disabled="busy.createGoal">{{ t('启动目标', 'Start goal') }}</button></form>
        <div class="goal-list"><div v-if="goals.length === 0" class="empty"><strong>{{ t('没有持续目标', 'No continuous goals') }}</strong><span>{{ t('目标会迭代执行，直至验收、预算耗尽或人工停止。', 'Goals iterate until accepted, budget-exhausted, or stopped by an operator.') }}</span></div><button v-for="goal in goals" :key="String(goal.goal_id)" type="button" class="goal-selector" :class="{ selected: selectedGoalId === goal.goal_id }" @click="selectGoal(String(goal.goal_id))"><span class="status" :class="status(goal.status).tone">{{ status(goal.status).label }}</span><strong>{{ goal.goal_text || goal.goal_id }}</strong><small>{{ goal.consumed_iterations || 0 }}/{{ goal.max_iterations || 0 }} {{ t('次迭代', 'iterations') }}</small></button><button v-if="goalCursor" class="load-more" type="button" :disabled="busy.moreGoals" @click="moreGoals">{{ t('加载更多', 'Load more') }}</button></div>

        <section v-if="selectedGoal" class="goal-detail" aria-live="polite"><header><div><p class="kicker">GOAL DETAIL</p><h4>{{ selectedGoal.goal_text }}</h4></div><div class="actions"><button v-if="selectedGoal.status === 'active'" type="button" @click="controlGoal('pause')">{{ t('暂停', 'Pause') }}</button><button v-if="selectedGoal.status === 'paused'" type="button" @click="controlGoal('resume')">{{ t('恢复', 'Resume') }}</button><button class="danger-text" type="button" @click="openGoalDialog('cancel')">{{ t('取消', 'Cancel') }}</button></div></header><div class="budget-grid"><article v-for="budget in goalBudgets" :key="budget.kind"><span>{{ budgetLabel(budget.kind) }}</span><strong>{{ formatBudget(budget.kind, budget.consumed) }} <small>/ {{ formatBudget(budget.kind, budget.maximum) }}</small></strong><div class="meter"><i :style="{ transform: `scaleX(${budget.percent / 100})` }" :class="{ exhausted: budget.exhausted }" /></div><em>{{ budget.percent }}%</em></article></div><div class="goal-columns"><div><div class="section-heading"><h4>{{ t('迭代记录', 'Iterations') }}</h4><span>{{ iterations.length }}</span></div><div v-if="iterations.length === 0" class="empty compact">{{ t('尚无迭代。', 'No iterations yet.') }}</div><article v-for="iteration in iterations" :key="String(iteration.iteration_id)" class="iteration-row"><span>#{{ iteration.sequence }}</span><strong>{{ status(iteration.state).label }}</strong><small>{{ t('尝试', 'Attempt') }} {{ Number(iteration.attempt || 0) + 1 }}</small></article></div><div><div class="section-heading"><h4>{{ t('操作员指导', 'Operator guidance') }}</h4><span>{{ guidance.length }}</span></div><form class="guidance-form" @submit.prevent="appendGuidance"><textarea v-model="guidanceDraft" maxlength="4096" :placeholder="t('补充约束或下一步建议', 'Add a constraint or next-step direction')" required /><button type="submit" :disabled="busy.guidance">{{ t('发送指导', 'Send guidance') }}</button></form><article v-for="item in guidance" :key="String(item.sequence)" class="guidance-row"><strong>#{{ item.sequence }}</strong><p>{{ item.content || '[REDACTED]' }}</p></article><button type="button" class="approval-button" @click="openGoalDialog('approve')">{{ t('批准预算调整', 'Approve budget adjustment') }}</button></div></div></section>
      </section>
    </template>

    <OperationalDialog :open="dialog.kind !== ''" :title="dialog.title" :description="dialog.description" :confirm-label="dialog.confirmLabel" :confirmation-phrase="dialog.phrase" :busy="dialogBusy" :error="dialogError" @cancel="closeDialog" @confirm="confirmDialog" />
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { AutonomicsApiError, autonomicsOperationsApi } from '@/api/autonomics'
import { isCurrentSelection, projectGoalBudgets, projectSchedulerRun, projectStatus, versionedMutation, type BudgetProjection } from '@/models/autonomics'
import { useSettingsStore } from '@/stores/settings'
import OperationalDialog from './OperationalDialog.vue'
import OperationalAccessPrompt from './OperationalAccessPrompt.vue'

type Mode = 'overview' | 'scheduler' | 'goals'
const settingsStore = useSettingsStore()
const tabs: Array<{ id: Mode; zh: string; en: string }> = [{ id: 'overview', zh: '总览', en: 'Overview' }, { id: 'scheduler', zh: '调度', en: 'Scheduler' }, { id: 'goals', zh: '目标', en: 'Goals' }]
const active = ref<Mode>('overview')
const loading = ref(false), error = ref(''), jobCursor = ref(''), selectedGoalId = ref(''), guidanceDraft = ref('')
const runCursor = ref(''), goalCursor = ref('')
const needsAccess = ref(false)
const health = ref<Record<string, unknown>>({}), jobs = ref<Record<string, unknown>[]>([]), runs = ref<Record<string, unknown>[]>([]), goals = ref<Record<string, unknown>[]>([]), iterations = ref<Record<string, unknown>[]>([]), guidance = ref<Record<string, unknown>[]>([])
const busy = reactive<Record<string, boolean>>({})
const jobDraft = reactive({ job_id: '', schedule: '0 9 * * *', timezone: 'Asia/Shanghai', prompt: '', max_retries: 5 })
const goalDraft = reactive({ session_id: '', goal_text: '', criteria: '', max_iterations: 20, max_tokens: 200000, max_estimated_cost: 100, max_active_seconds: 86400 })
const dialog = reactive({ kind: '', title: '', description: '', confirmLabel: '', phrase: '' })
const dialogBusy = ref(false), dialogError = ref('')
let controller: AbortController | null = null, epoch = 0
let detailController: AbortController | null = null, detailEpoch = 0
let pendingMutation: ((reauthentication: string) => Promise<unknown>) | null = null

const healthReady = computed(() => health.value.ready === true)
const workers = computed(() => {
  const value = health.value.workers
  if (!value || typeof value !== 'object' || Array.isArray(value)) return []
  return Object.entries(value as Record<string, unknown>).map(([name, raw]) => {
    const item = raw && typeof raw === 'object' ? raw as Record<string, unknown> : {}
    return { name, ready: item.ready !== false && item.running !== false, detail: String(item.status ?? item.last_error ?? 'ready') }
  })
})
const workerSummary = computed(() => t(`${workers.value.filter(item => item.ready).length}/${workers.value.length} 个工作器就绪`, `${workers.value.filter(item => item.ready).length}/${workers.value.length} workers ready`))
const activeJobs = computed(() => jobs.value.filter(item => item.status === 'active').length)
const activeGoals = computed(() => goals.value.filter(item => ['active', 'running', 'blocked'].includes(String(item.status))).length)
const runViews = computed(() => runs.value.map(item => projectSchedulerRun(item, 'operator')))
const selectedGoal = computed(() => goals.value.find(item => item.goal_id === selectedGoalId.value) ?? null)
const goalBudgets = computed(() => projectGoalBudgets(selectedGoal.value ?? {}))

function t(zh: string, en: string): string { return settingsStore.t(zh, en) }
function status(value: unknown) { return projectStatus(value) }
function message(value: unknown): string { return value instanceof AutonomicsApiError ? value.message : value instanceof Error ? value.message : t('请求失败', 'Request failed') }
function isBusy(id: string): boolean { return busy[id] === true }
function formatDate(value: unknown): string { const date = new Date(String(value ?? '')); return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString() }
function budgetLabel(kind: BudgetProjection['kind']): string { return ({ iterations: t('迭代', 'Iterations'), tokens: 'Tokens', cost: t('估算成本', 'Estimated cost'), active_time: t('活动时间', 'Active time') })[kind] }
function formatBudget(kind: BudgetProjection['kind'], value: number): string { if (kind === 'cost') return `$${value.toFixed(2)}`; if (kind === 'active_time') return `${Math.round(value)}s`; return Math.round(value).toLocaleString() }

async function loadAll(): Promise<void> {
  controller?.abort(); detailController?.abort(); controller = new AbortController(); const requestEpoch = ++epoch; loading.value = true; error.value = ''
  try {
    const [healthValue, jobPage, runPage, goalPage] = await Promise.all([autonomicsOperationsApi.health(controller.signal), autonomicsOperationsApi.listJobs('', controller.signal), autonomicsOperationsApi.listRuns('', controller.signal), autonomicsOperationsApi.listGoals('', controller.signal)])
    if (requestEpoch !== epoch) return
    health.value = healthValue; jobs.value = jobPage.items; jobCursor.value = jobPage.nextCursor; runs.value = runPage.items; runCursor.value = runPage.nextCursor; goals.value = goalPage.items; goalCursor.value = goalPage.nextCursor
    if (selectedGoalId.value && !goals.value.some(item => item.goal_id === selectedGoalId.value)) selectedGoalId.value = ''
    if (selectedGoalId.value) await loadGoalDetail(selectedGoalId.value)
  } catch (cause) { if (!(cause instanceof DOMException && cause.name === 'AbortError') && requestEpoch === epoch) { needsAccess.value = cause instanceof AutonomicsApiError && ['operational_bootstrap_required', 'bootstrap_capability_required', 'authentication_required'].includes(cause.code); error.value = message(cause) } }
  finally { if (requestEpoch === epoch) loading.value = false }
}
function accessConnected(): void { needsAccess.value = false; void loadAll() }
async function mutate(key: string, action: (reauthentication?: string) => Promise<unknown>, refresh = true, onSuccess: () => void = () => {}): Promise<boolean> { busy[key] = true; error.value = ''; const complete = async (reauthentication?: string) => { await action(reauthentication); onSuccess(); if (refresh) await loadAll() }; try { await complete(); return true } catch (cause) { if (cause instanceof AutonomicsApiError && cause.code === 'recent_reauthentication_required') { pendingMutation = reauthentication => complete(reauthentication); Object.assign(dialog, { kind: 'reauthRetry', title: t('重新认证后继续', 'Reauthenticate to continue'), description: t('短期认证已超过敏感操作窗口。确认用户在场后，只重试这一次被服务端拒绝的操作。', 'The short-lived authentication is outside the sensitive-action window. After confirming user presence, only this server-rejected action is retried.'), confirmLabel: t('认证并继续', 'Reauthenticate and continue'), phrase: '' }) } else error.value = message(cause); return false } finally { busy[key] = false } }
async function createJob(): Promise<void> { const draft = { ...jobDraft }; await mutate('createJob', reauth => autonomicsOperationsApi.createJob(draft, { reauthentication: reauth }), true, () => { jobDraft.job_id = ''; jobDraft.prompt = '' }) }
async function toggleJob(job: Record<string, unknown>): Promise<void> { const id = String(job.job_id); await mutate(id, reauth => autonomicsOperationsApi.updateJob(id, versionedMutation({ status: job.status === 'active' ? 'paused' : 'active' }, Number(job.runtime_version ?? 0)), { reauthentication: reauth })) }
async function triggerJob(id: string): Promise<void> { await mutate(id, reauth => autonomicsOperationsApi.triggerJob(id, { reauthentication: reauth })) }
async function moreJobs(): Promise<void> { if (busy.moreJobs) return; busy.moreJobs = true; try { const requestEpoch = epoch; const page = await autonomicsOperationsApi.listJobs(jobCursor.value, controller?.signal); if (requestEpoch !== epoch || active.value !== 'scheduler') return; jobs.value = [...jobs.value, ...page.items]; jobCursor.value = page.nextCursor } finally { busy.moreJobs = false } }
async function moreRuns(): Promise<void> { if (busy.moreRuns) return; busy.moreRuns = true; try { const requestEpoch = epoch; const page = await autonomicsOperationsApi.listRuns(runCursor.value, controller?.signal); if (requestEpoch !== epoch || active.value !== 'scheduler') return; runs.value = [...runs.value, ...page.items]; runCursor.value = page.nextCursor } finally { busy.moreRuns = false } }
async function moreGoals(): Promise<void> { if (busy.moreGoals) return; busy.moreGoals = true; try { const requestEpoch = epoch; const page = await autonomicsOperationsApi.listGoals(goalCursor.value, controller?.signal); if (requestEpoch !== epoch || active.value !== 'goals') return; goals.value = [...goals.value, ...page.items]; goalCursor.value = page.nextCursor } finally { busy.moreGoals = false } }
async function createGoal(): Promise<void> { const draft = { session_id: goalDraft.session_id, goal_text: goalDraft.goal_text, acceptance_criteria: goalDraft.criteria.split(/\r?\n/).map(item => item.trim()).filter(Boolean), max_iterations: goalDraft.max_iterations, max_tokens: goalDraft.max_tokens, max_estimated_cost: goalDraft.max_estimated_cost, max_active_seconds: goalDraft.max_active_seconds }; await mutate('createGoal', reauth => autonomicsOperationsApi.createGoal(draft, { reauthentication: reauth }), true, () => { goalDraft.goal_text = ''; goalDraft.criteria = '' }) }
async function loadGoalDetail(id: string): Promise<void> {
  detailController?.abort(); detailController = new AbortController(); const requestEpoch = ++detailEpoch
  const [iterationRows, guidanceRows] = await Promise.all([autonomicsOperationsApi.iterations(id, detailController.signal), autonomicsOperationsApi.guidance(id, detailController.signal)])
  if (!isCurrentSelection(id, selectedGoalId.value, requestEpoch, detailEpoch)) return
  iterations.value = iterationRows; guidance.value = guidanceRows
}
async function selectGoal(id: string): Promise<void> { selectedGoalId.value = id; iterations.value = []; guidance.value = []; try { await loadGoalDetail(id) } catch (cause) { if (!(cause instanceof DOMException && cause.name === 'AbortError')) error.value = message(cause) } }
async function appendGuidance(): Promise<void> { if (!selectedGoalId.value) return; const goalId = selectedGoalId.value; const content = guidanceDraft.value; await mutate('guidance', reauth => autonomicsOperationsApi.appendGuidance(goalId, { content }, { reauthentication: reauth }), true, () => { guidanceDraft.value = '' }) }
async function controlGoal(action: 'pause' | 'resume'): Promise<void> { if (!selectedGoal.value) return; const id = String(selectedGoal.value.goal_id); await mutate(id, reauth => autonomicsOperationsApi.controlGoal(id, { action, expected_version: Number(selectedGoal.value?.runtime_version ?? 0), reason: `operator ${action}` }, { reauthentication: reauth })) }
function openGoalDialog(kind: 'cancel' | 'approve'): void { if (!selectedGoalId.value) return; Object.assign(dialog, kind === 'cancel' ? { kind, title: t('取消持续目标', 'Cancel continuous goal'), description: t('正在运行的迭代会在安全边界停止，目标不可自动恢复。', 'The active iteration stops at a safe boundary and the goal will not resume automatically.'), confirmLabel: t('取消目标', 'Cancel goal'), phrase: selectedGoalId.value } : { kind, title: t('批准预算调整', 'Approve a budget adjustment'), description: t('签发一个短期操作员批准，允许目标按当前预算继续恢复。', 'Issue a short-lived operator approval allowing the goal to resume under its current budget.'), confirmLabel: t('签发批准', 'Issue approval'), phrase: selectedGoalId.value }) }
function closeDialog(): void { if (dialog.kind === 'reauthRetry') pendingMutation = null; Object.assign(dialog, { kind: '', title: '', description: '', confirmLabel: '', phrase: '' }); dialogError.value = '' }
async function confirmDialog(payload: { reauthentication: string; sensitiveValue: string }): Promise<void> {
  if (dialog.kind !== 'reauthRetry' && !selectedGoal.value) return
  dialogBusy.value = true; dialogError.value = ''
  const isRetry = dialog.kind === 'reauthRetry'
  const id = String(selectedGoal.value?.goal_id ?? ''); const version = Number(selectedGoal.value?.runtime_version ?? 0)
  try {
    if (dialog.kind === 'reauthRetry') {
      if (!pendingMutation) throw new Error(t('待处理操作已失效', 'The pending operation expired'))
      const retry = pendingMutation; pendingMutation = null
      await retry(payload.reauthentication)
    } else if (dialog.kind === 'cancel') await autonomicsOperationsApi.controlGoal(id, { action: 'cancel', expected_version: version, reason: 'operator cancellation' }, { reauthentication: payload.reauthentication })
    else await autonomicsOperationsApi.approveGoal(id, { approval_id: `ui-${Date.now().toString(36)}`, decision: 'reset_failures', expected_goal_version: version, expires_in_seconds: 300, budget_updates: {} }, { reauthentication: payload.reauthentication })
    closeDialog(); if (!isRetry) await loadAll()
  } catch (cause) { dialogError.value = message(cause) } finally { dialogBusy.value = false }
}

onMounted(() => void loadAll())
onBeforeUnmount(() => { controller?.abort(); detailController?.abort(); pendingMutation = null; guidanceDraft.value = ''; closeDialog() })
</script>

<style scoped>
.autonomics-page { display: grid; gap: 18px; min-width: 0; color: var(--text-primary); }
.page-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; padding-bottom: 15px; border-bottom: 1px solid var(--border-color); }
.kicker { margin: 0 0 6px; color: #28736b; font: 700 11px/1.2 ui-monospace, SFMono-Regular, Consolas, monospace; letter-spacing: .09em; }
h3, h4 { margin: 0; letter-spacing: -.025em; } h3 { font-size: 21px; } h4 { font-size: 14px; }
.page-header p:last-child, .resource-row p { margin: 6px 0 0; color: var(--text-muted); font-size: 12px; line-height: 1.5; }
button { min-height: 34px; padding: 0 11px; border: 1px solid var(--border-color); border-radius: 8px; background: transparent; color: var(--text-secondary); cursor: pointer; font: inherit; } button:active:not(:disabled) { transform: translateY(1px); } button:disabled { cursor: not-allowed; opacity: .5; } button:focus-visible, input:focus, textarea:focus { outline: 2px solid color-mix(in srgb, #2d766e 45%, transparent); outline-offset: 2px; }
.health-strip { display: flex; align-items: center; justify-content: space-between; gap: 15px; padding: 13px 15px; border-left: 3px solid #2d766e; background: color-mix(in srgb, #2d766e 7%, transparent); } .health-strip.degraded { border-color: #ad4939; background: color-mix(in srgb, #ad4939 7%, transparent); } .health-strip > div { display: flex; align-items: center; gap: 9px; } .health-strip small, .worker-row small { color: var(--text-muted); } .health-strip code { font-size: 11px; }
.health-mark { width: 8px; height: 8px; border-radius: 50%; background: #2d766e; } .health-mark.off, .degraded .health-mark { background: #ad4939; }
.mode-tabs { display: flex; gap: 4px; width: fit-content; padding: 3px; border: 1px solid var(--border-color); border-radius: 11px; } .mode-tabs button { border: 0; } .mode-tabs button[aria-selected="true"] { background: #2d766e; color: white; }
.overview-grid { display: grid; grid-template-columns: .8fr 1.3fr .8fr; gap: 1px; background: var(--border-color); border: 1px solid var(--border-color); } .metric-block { display: grid; gap: 5px; padding: 20px; background: var(--panel-bg, #f8f9fa); } .metric-block span, .metric-block small { color: var(--text-muted); font-size: 11px; } .metric-block strong { font: 700 25px/1.1 ui-monospace, SFMono-Regular, Consolas, monospace; } .worker-list { grid-column: 1/-1; padding: 18px; background: var(--panel-bg, #f8f9fa); } .worker-list h4 { margin-bottom: 8px; } .worker-row { display: flex; align-items: center; gap: 10px; padding: 10px 0; border-top: 1px solid var(--border-color); } .worker-row div { display: flex; justify-content: space-between; gap: 12px; width: 100%; }
.split-layout { display: grid; grid-template-columns: minmax(250px, .72fr) minmax(330px, 1.28fr); gap: 20px; } .runs-panel { grid-column: 1/-1; }
.editor { display: grid; gap: 13px; align-self: start; padding: 17px; border: 1px solid var(--border-color); border-radius: 13px; background: color-mix(in srgb, var(--glass-bg-strong) 72%, transparent); } label { display: grid; gap: 6px; color: var(--text-secondary); font-size: 12px; } input, textarea { min-width: 0; box-sizing: border-box; width: 100%; padding: 9px 10px; border: 1px solid var(--border-color); border-radius: 8px; background: var(--input-bg, rgba(255,255,255,.55)); color: var(--text-primary); } textarea { min-height: 80px; resize: vertical; } .field-pair { display: grid; grid-template-columns: 1fr 1fr; gap: 9px; } .primary { min-height: 38px; border: 0; background: #2d766e; color: white; font-weight: 650; }
.resource-list, .goal-list { display: grid; align-content: start; } .resource-row { display: flex; align-items: center; justify-content: space-between; gap: 14px; padding: 14px 3px; border-bottom: 1px solid var(--border-color); } .resource-row strong { overflow-wrap: anywhere; } .actions { display: flex; flex-wrap: wrap; gap: 7px; } .status { display: inline-block; margin-right: 7px; padding: 3px 6px; border-radius: 5px; background: var(--hover-bg); color: var(--text-muted); font: 650 10px/1.2 ui-monospace, monospace; text-transform: uppercase; } .status.active { background: #dceeea; color: #256c64; } .status.success { background: #dfede1; color: #2f7040; } .status.warning { background: #f4ead2; color: #86611e; } .status.danger { background: #f6dfdb; color: #a13e32; }
.runs-panel { border-top: 1px solid var(--border-color); } .section-heading { display: flex; align-items: center; justify-content: space-between; padding: 13px 2px; } .section-heading span { color: var(--text-muted); font: 12px ui-monospace, monospace; } .run-row { display: grid; grid-template-columns: auto 1fr auto; align-items: center; gap: 10px; padding: 11px 2px; border-top: 1px solid var(--border-color); } .run-row div { display: grid; gap: 3px; } .run-row small, .run-row time { color: var(--text-muted); font-size: 11px; }
.goals-layout { display: grid; grid-template-columns: minmax(240px, .7fr) minmax(290px, 1.3fr); gap: 20px; align-items: start; } .goal-editor { grid-row: span 2; } .budget-inputs { display: grid; grid-template-columns: 1fr 1fr; gap: 9px; } .goal-selector { display: grid; justify-items: start; gap: 5px; height: auto; padding: 13px 8px; border: 0; border-bottom: 1px solid var(--border-color); border-radius: 0; text-align: left; } .goal-selector.selected { border-left: 3px solid #2d766e; padding-left: 12px; background: color-mix(in srgb, #2d766e 6%, transparent); } .goal-selector strong { max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } .goal-selector small { color: var(--text-muted); }
.goal-detail { grid-column: 1/-1; display: grid; gap: 16px; padding-top: 17px; border-top: 1px solid var(--border-color); } .goal-detail > header { display: flex; justify-content: space-between; gap: 12px; } .danger-text { color: #a94537; } .budget-grid { display: grid; grid-template-columns: 1.25fr .85fr 1.1fr .8fr; gap: 1px; border: 1px solid var(--border-color); background: var(--border-color); } .budget-grid article { display: grid; gap: 7px; padding: 13px; background: var(--panel-bg, #f8f9fa); } .budget-grid span, .budget-grid em { color: var(--text-muted); font-size: 10px; font-style: normal; } .budget-grid strong { font: 700 15px ui-monospace, monospace; } .budget-grid strong small { color: var(--text-muted); } .meter { height: 4px; overflow: hidden; border-radius: 2px; background: var(--hover-bg); } .meter i { display: block; width: 100%; height: 100%; transform-origin: left; background: #2d766e; } .meter i.exhausted { background: #ad4939; }
.goal-columns { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; } .iteration-row { display: grid; grid-template-columns: 42px 1fr auto; gap: 9px; padding: 9px 1px; border-top: 1px solid var(--border-color); font-size: 12px; } .iteration-row span, .iteration-row small { color: var(--text-muted); } .guidance-form { display: grid; gap: 7px; } .guidance-form textarea { min-height: 62px; } .guidance-row { padding: 9px 1px; border-top: 1px solid var(--border-color); } .guidance-row p { margin: 5px 0 0; color: var(--text-secondary); font-size: 12px; line-height: 1.5; } .approval-button { width: 100%; margin-top: 10px; }
.empty { display: grid; gap: 6px; padding: 35px 6px; color: var(--text-muted); font-size: 12px; } .empty strong { color: var(--text-primary); font-size: 14px; } .empty.compact { padding: 15px 2px; }
.error-panel { display: grid; gap: 8px; padding: 18px; border: 1px solid color-mix(in srgb, #ad4939 45%, var(--border-color)); border-radius: 12px; } .error-panel span { color: var(--text-muted); font-size: 12px; }
.skeleton-grid { display: grid; grid-template-columns: 1fr 1.4fr; gap: 10px; } .skeleton-grid i { height: 75px; border-radius: 9px; background: var(--hover-bg); } .skeleton-grid i:last-child { grid-column: 1/-1; }
@media (max-width: 720px) { .page-header, .health-strip, .health-strip > div, .resource-row, .goal-detail > header { align-items: stretch; flex-direction: column; } .overview-grid, .split-layout, .goals-layout, .goal-columns, .budget-grid, .field-pair, .budget-inputs { grid-template-columns: minmax(0, 1fr); } .goal-editor, .goal-detail, .runs-panel { grid-column: 1; grid-row: auto; } .actions, .actions button { width: 100%; } .run-row { grid-template-columns: auto 1fr; } .run-row time { grid-column: 2; } }
@media (prefers-reduced-motion: reduce) { button { transition: none; } }
</style>
