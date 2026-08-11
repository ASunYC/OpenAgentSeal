<template>
  <section class="operations-page" aria-labelledby="channels-title">
    <header class="operations-header">
      <div>
        <p class="kicker">MESSAGE GATEWAY</p>
        <h3 id="channels-title">{{ t('渠道与可靠投递', 'Channels & reliable delivery') }}</h3>
        <p>{{ t('管理官方渠道、路由、投递异常与保留策略。凭据始终只写。', 'Manage official channels, routes, delivery exceptions, and retention. Credentials are always write-only.') }}</p>
      </div>
      <button class="quiet-button" type="button" :disabled="loading" @click="loadActive">{{ t('刷新', 'Refresh') }}</button>
    </header>

    <div class="section-tabs" role="tablist" :aria-label="t('渠道管理区域', 'Channel administration sections')" @keydown="onTabKeydown">
      <button v-for="tab in tabs" :id="`channel-tab-${tab.id}`" :key="tab.id" role="tab" :aria-selected="active === tab.id" :tabindex="active === tab.id ? 0 : -1" @click="selectTab(tab.id)">{{ t(tab.zh, tab.en) }}</button>
    </div>

    <p class="screen-reader-live" aria-live="polite">{{ liveMessage }}</p>
    <OperationalAccessPrompt v-if="needsAccess" @connected="accessConnected" />
    <div v-else-if="loading" class="skeleton-stack" aria-label="Loading"><i v-for="item in 4" :key="item" /></div>
    <div v-else-if="error" class="state-panel error" role="alert">
      <strong>{{ t('无法加载运营数据', 'Could not load operational data') }}</strong><span>{{ error }}</span><button type="button" @click="loadActive">{{ t('重试', 'Retry') }}</button>
    </div>

    <template v-else>
      <section v-if="active === 'accounts'" class="content-grid" role="tabpanel" aria-labelledby="channel-tab-accounts">
        <form class="editor-panel" @submit.prevent="openCreate">
          <h4>{{ t('连接官方渠道', 'Connect an official channel') }}</h4>
          <label><span>{{ t('账户标识', 'Account ID') }}</span><input v-model.trim="accountDraft.account_id" maxlength="128" required /></label>
          <label><span>{{ t('适配器', 'Adapter') }}</span><select v-model="accountDraft.adapter_kind"><option v-for="adapter in adapters" :key="adapter" :value="adapter">{{ adapter }}</option></select></label>
          <label><span>{{ t('默认智能体配置', 'Default agent profile') }}</span><input v-model.trim="accountDraft.default_profile_id" maxlength="128" placeholder="main" /></label>
          <label><span>{{ t('凭据（仅写入）', 'Credential (write-only)') }}</span><textarea v-model="accountDraft.credential" autocomplete="off" spellcheck="false" required /><small>{{ t('保存后不会再次显示或写入浏览器存储。', 'It will never be displayed again or written to browser storage.') }}</small></label>
          <button class="primary-button" :disabled="busy.create" type="submit">{{ busy.create ? t('连接中…', 'Connecting…') : t('连接渠道', 'Connect channel') }}</button>
        </form>
        <div class="list-panel">
          <div v-if="accounts.length === 0" class="empty-state"><strong>{{ t('尚无渠道账户', 'No channel accounts') }}</strong><span>{{ t('使用左侧表单连接第一个官方机器人账户。', 'Use the form to connect the first official bot account.') }}</span></div>
          <article v-for="account in accountViews" :key="account.id" class="resource-row">
            <div><span class="status-dot" :class="account.enabled ? 'active' : 'muted'" /><strong>{{ account.id }}</strong><p>{{ account.adapter }} · {{ account.credential.configured ? t('凭据已配置', 'Credential configured') : t('缺少凭据', 'Credential missing') }}</p></div>
            <div class="row-actions">
              <button type="button" :disabled="isBusy(account.id)" @click="toggleAccount(account)">{{ account.enabled ? t('停用', 'Disable') : t('启用', 'Enable') }}</button>
              <button type="button" :disabled="isBusy(account.id)" @click="openCredential(account.id, account.version)">{{ t('轮换凭据', 'Rotate credential') }}</button>
              <button class="danger-text" type="button" :disabled="isBusy(account.id)" @click="openDelete(account.id)">{{ t('删除', 'Delete') }}</button>
            </div>
          </article>
          <button v-if="nextCursor" class="load-more" type="button" :disabled="busy.moreAccounts" @click="loadMoreAccounts">{{ t('加载更多', 'Load more') }}</button>
        </div>
      </section>

      <section v-if="active === 'routes'" class="content-grid" role="tabpanel" aria-labelledby="channel-tab-routes">
        <form class="editor-panel" @submit.prevent="openRoute">
          <h4>{{ t('会话路由', 'Conversation route') }}</h4>
          <label><span>{{ t('渠道账户', 'Channel account') }}</span><select v-model="routeDraft.account_id" required><option value="" disabled>{{ t('选择账户', 'Select account') }}</option><option v-for="account in accounts" :key="String(account.account_id)" :value="String(account.account_id)">{{ account.account_id }}</option></select></label>
          <label><span>{{ t('会话标识', 'Conversation ID') }}</span><input v-model.trim="routeDraft.conversation_id" maxlength="256" required /></label>
          <label><span>{{ t('发送者标识（可选）', 'Sender ID (optional)') }}</span><input v-model.trim="routeDraft.sender_id" maxlength="256" /></label>
          <label><span>{{ t('智能体配置', 'Agent profile') }}</span><input v-model.trim="routeDraft.profile_id" maxlength="128" placeholder="main" /></label>
          <label><span>{{ t('群聊触发策略', 'Group trigger policy') }}</span><select v-model="routeDraft.trigger_policy"><option value="default">default</option><option value="mention">mention</option><option value="reply">reply</option><option value="always">always</option><option value="never">never</option></select></label>
          <button class="primary-button" type="submit" :disabled="busy.route">{{ t('保存路由', 'Save route') }}</button>
        </form>
        <div class="list-panel"><div v-if="routes.length === 0" class="empty-state"><strong>{{ t('没有匹配的路由', 'No routes configured') }}</strong><span>{{ t('路由决定每个会话使用哪个智能体。', 'Routes decide which agent handles a conversation.') }}</span></div><article v-for="route in routes" :key="String(route.route_id)" class="resource-row"><div><strong>{{ route.route_id }}</strong><p>{{ route.trigger_policy }} · {{ route.profile_id || 'default profile' }}</p></div><button type="button" class="danger-text" @click="openDeleteRoute(String(route.route_id))">{{ t('移除', 'Remove') }}</button></article></div>
      </section>

      <section v-if="active === 'inbox'" class="list-panel full" role="tabpanel" aria-labelledby="channel-tab-inbox">
        <div v-if="inbox.length === 0" class="empty-state"><strong>{{ t('收件箱为空', 'Inbox is empty') }}</strong><span>{{ t('已认证的渠道事件会在这里留下脱敏记录。', 'Authenticated channel events leave redacted records here.') }}</span></div>
        <article v-for="item in inbox" :key="String(item.event_id)" class="resource-row"><div><strong>{{ item.event_id }}</strong><p>{{ item.account_id }} · {{ item.state }}</p></div><code>{{ formatDate(item.updated_at) }}</code></article>
        <button v-if="inboxCursor" class="load-more" type="button" :disabled="busy.moreInbox" @click="loadMoreRecords('inbox')">{{ t('加载更多', 'Load more') }}</button>
      </section>

      <section v-if="active === 'deliveries'" class="list-panel full" role="tabpanel" aria-labelledby="channel-tab-deliveries">
        <div v-if="deliveries.length === 0" class="empty-state"><strong>{{ t('没有投递记录', 'No delivery records') }}</strong><span>{{ t('结果发送及确认状态会在这里显示。', 'Result delivery and acknowledgement states appear here.') }}</span></div>
        <article v-for="delivery in deliveryViews" :key="delivery.id" class="resource-row" :class="`risk-${delivery.risk}`"><div><span class="status-label" :class="delivery.status.tone">{{ delivery.status.label }}</span><strong>{{ delivery.id }}</strong><p>{{ t('尝试次数', 'Attempt') }} {{ delivery.attemptNumber }}<template v-if="delivery.warningCode"> · {{ t('可能已远端送达，禁止自动重发', 'May be remotely delivered; automatic resend is disabled') }}</template></p></div><button v-if="delivery.status.value === 'delivery_unknown' || delivery.status.value === 'dead_letter'" type="button" :disabled="isBusy(delivery.id)" @click="openResend(delivery)">{{ t('人工协调', 'Reconcile') }}</button></article>
        <button v-if="deliveryCursor" class="load-more" type="button" :disabled="busy.moreDeliveries" @click="loadMoreRecords('deliveries')">{{ t('加载更多', 'Load more') }}</button>
      </section>

      <section v-if="active === 'audit'" class="list-panel full" role="tabpanel" aria-labelledby="channel-tab-audit">
        <div class="privacy-note">{{ t('默认视图已脱敏。临时揭示仅保存在内存，离开本页即清除。', 'This view is redacted by default. Temporary reveals stay in memory and are cleared when you leave.') }}</div>
        <div v-if="audit.length === 0" class="empty-state"><strong>{{ t('暂无审计事件', 'No audit events') }}</strong></div>
        <article v-for="item in audit" :key="String(item.audit_id)" class="resource-row"><div><strong>{{ item.action }}</strong><p>{{ item.entity_kind }} · {{ item.entity_id }}</p><pre v-if="revealedAudit[String(item.audit_id)]">{{ revealedAudit[String(item.audit_id)] }}</pre></div><button type="button" @click="openRevealAudit(String(item.audit_id))">{{ t('临时揭示安全字段', 'Reveal safe fields temporarily') }}</button></article>
        <button v-if="auditCursor" class="load-more" type="button" :disabled="busy.moreAudit" @click="loadMoreRecords('audit')">{{ t('加载更多', 'Load more') }}</button>
      </section>

      <section v-if="active === 'retention'" class="content-grid" role="tabpanel" aria-labelledby="channel-tab-retention">
        <form class="editor-panel" @submit.prevent="saveRetention"><h4>{{ t('数据保留期限', 'Data retention') }}</h4><label v-for="field in retentionFields" :key="field.key"><span>{{ t(field.zh, field.en) }}</span><input v-model.number="retention[field.key]" type="number" min="1" max="3650" required /></label><div class="inline-actions"><button class="primary-button" type="submit" :disabled="busy.retention">{{ t('保存', 'Save') }}</button><button type="button" :disabled="busy.retention" @click="runRetention">{{ t('立即执行', 'Run now') }}</button></div></form>
        <div class="list-panel"><h4>{{ t('保留任务死信', 'Retention dead letters') }}</h4><div v-if="retentionDeadLetters.length === 0" class="empty-state compact"><span>{{ t('没有待处理死信。', 'No dead letters need attention.') }}</span></div><article v-for="item in retentionDeadLetters" :key="String(item.dead_letter_id)" class="resource-row"><div><strong>{{ item.dead_letter_id }}</strong><p>{{ item.state }}</p></div><button type="button" @click="requeueRetention(String(item.dead_letter_id))">{{ t('重新入队', 'Requeue') }}</button></article></div>
      </section>
    </template>

    <OperationalDialog :open="dialog.kind !== ''" :title="dialog.title" :description="dialog.description" :confirm-label="dialog.confirmLabel" :confirmation-phrase="dialog.phrase" :sensitive-label="dialog.sensitiveLabel" :busy="dialogBusy" :error="dialogError" @cancel="closeDialog" @confirm="confirmDialog" />
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { AutonomicsApiError, channelsOperationsApi } from '@/api/autonomics'
import { projectChannelAccount, projectDelivery, versionedMutation, type ChannelAccountProjection, type DeliveryProjection } from '@/models/autonomics'
import { useSettingsStore } from '@/stores/settings'
import OperationalDialog from './OperationalDialog.vue'
import OperationalAccessPrompt from './OperationalAccessPrompt.vue'

type TabId = 'accounts' | 'routes' | 'inbox' | 'deliveries' | 'audit' | 'retention'
const settingsStore = useSettingsStore()
const tabs: Array<{ id: TabId; zh: string; en: string }> = [
  { id: 'accounts', zh: '账户', en: 'Accounts' }, { id: 'routes', zh: '路由', en: 'Routes' },
  { id: 'inbox', zh: '收件箱', en: 'Inbox' }, { id: 'deliveries', zh: '投递与死信', en: 'Delivery & dead letters' },
  { id: 'audit', zh: '审计', en: 'Audit' }, { id: 'retention', zh: '保留', en: 'Retention' },
]
const adapters = ['telegram', 'discord', 'slack', 'whatsapp', 'feishu', 'dingtalk', 'line', 'qq', 'wecom']
const active = ref<TabId>('accounts')
const loading = ref(false)
const error = ref('')
const liveMessage = ref('')
const needsAccess = ref(false)
const accounts = ref<Record<string, unknown>[]>([])
const routes = ref<Record<string, unknown>[]>([])
const inbox = ref<Record<string, unknown>[]>([])
const deliveries = ref<Record<string, unknown>[]>([])
const audit = ref<Record<string, unknown>[]>([])
const retentionDeadLetters = ref<Record<string, unknown>[]>([])
const nextCursor = ref('')
const inboxCursor = ref(''), deliveryCursor = ref(''), auditCursor = ref('')
const busy = reactive<Record<string, boolean>>({})
const revealedAudit = reactive<Record<string, string>>({})
const retention = reactive<Record<'inbox_days' | 'outbox_days' | 'audit_days' | 'version', number>>({ inbox_days: 30, outbox_days: 30, audit_days: 90, version: 0 })
const retentionFields = [
  { key: 'inbox_days' as const, zh: '收件箱天数', en: 'Inbox days' },
  { key: 'outbox_days' as const, zh: '投递记录天数', en: 'Delivery days' },
  { key: 'audit_days' as const, zh: '审计天数', en: 'Audit days' },
]
const accountDraft = reactive({ account_id: '', adapter_kind: 'telegram', default_profile_id: 'main', credential: '' })
const routeDraft = reactive({ account_id: '', conversation_id: '', sender_id: '', profile_id: 'main', trigger_policy: 'default' })
const dialog = reactive({ kind: '', target: '', version: 0, title: '', description: '', confirmLabel: '', phrase: '', sensitiveLabel: '' })
const dialogBusy = ref(false)
const dialogError = ref('')
let controller: AbortController | null = null
let epoch = 0
let routeController: AbortController | null = null
let routeEpoch = 0
let pendingMutation: ((reauthentication: string) => Promise<unknown>) | null = null

const accountViews = computed(() => accounts.value.map(projectChannelAccount))
const deliveryViews = computed(() => deliveries.value.map(item => projectDelivery(item, 'operator')))

function t(zh: string, en: string): string { return settingsStore.t(zh, en) }
function message(value: unknown): string { return value instanceof AutonomicsApiError ? value.message : value instanceof Error ? value.message : t('请求失败', 'Request failed') }
function isBusy(id: string): boolean { return busy[id] === true }
function formatDate(value: unknown): string { const date = new Date(String(value ?? '')); return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString() }
function clearReveals(): void { for (const key of Object.keys(revealedAudit)) delete revealedAudit[key] }

function selectTab(tab: TabId): void { if (active.value === 'audit' && tab !== 'audit') clearReveals(); active.value = tab }
function onTabKeydown(event: KeyboardEvent): void {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
  const items = [...(event.currentTarget as HTMLElement).querySelectorAll<HTMLButtonElement>('[role="tab"]')]
  if (items.length === 0) return
  const current = items.indexOf(document.activeElement as HTMLButtonElement)
  const index = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : event.key === 'ArrowRight' ? (current + 1) % items.length : (current - 1 + items.length) % items.length
  event.preventDefault(); items[index]?.focus(); items[index]?.click()
}

async function loadRoutesForAccount(accountId: string): Promise<void> {
  routeController?.abort(); routeController = new AbortController(); const requestEpoch = ++routeEpoch
  if (!accountId) { routes.value = []; return }
  const rows = await channelsOperationsApi.listRoutes(accountId, routeController.signal)
  if (requestEpoch === routeEpoch && routeDraft.account_id === accountId) routes.value = rows
}

async function loadActive(): Promise<void> {
  controller?.abort()
  controller = new AbortController()
  const requestEpoch = ++epoch
  loading.value = true
  error.value = ''
  try {
    if (active.value === 'accounts' || active.value === 'routes') {
      const page = await channelsOperationsApi.listAccounts('', controller.signal)
      if (requestEpoch !== epoch) return
      accounts.value = page.items
      nextCursor.value = page.nextCursor
      if (active.value === 'routes' && routeDraft.account_id) await loadRoutesForAccount(routeDraft.account_id)
    } else if (active.value === 'inbox') { const page = await channelsOperationsApi.listInbox('', controller.signal); inbox.value = page.items; inboxCursor.value = page.nextCursor }
    else if (active.value === 'deliveries') { const page = await channelsOperationsApi.listOutbox('', controller.signal); deliveries.value = page.items; deliveryCursor.value = page.nextCursor }
    else if (active.value === 'audit') { const page = await channelsOperationsApi.listAudit('', controller.signal); audit.value = page.items; auditCursor.value = page.nextCursor }
    else {
      const [policy, deadLetters] = await Promise.all([channelsOperationsApi.getRetention(controller.signal), channelsOperationsApi.listRetentionDeadLetters(controller.signal)])
      for (const key of ['inbox_days', 'outbox_days', 'audit_days', 'version'] as const) retention[key] = Number(policy[key] ?? retention[key])
      retentionDeadLetters.value = deadLetters
    }
    if (requestEpoch === epoch) liveMessage.value = t('运营数据已更新', 'Operational data updated')
  } catch (cause) {
    if (!(cause instanceof DOMException && cause.name === 'AbortError') && requestEpoch === epoch) {
      needsAccess.value = cause instanceof AutonomicsApiError && ['operational_bootstrap_required', 'bootstrap_capability_required', 'authentication_required'].includes(cause.code)
      error.value = message(cause)
    }
  } finally { if (requestEpoch === epoch) loading.value = false }
}

function accessConnected(): void { needsAccess.value = false; void loadActive() }

async function mutate(key: string, action: (reauthentication?: string) => Promise<unknown>, reload = true): Promise<boolean> {
  busy[key] = true; error.value = ''
  try { await action(); if (reload) await loadActive(); return true }
  catch (cause) {
    if (cause instanceof AutonomicsApiError && cause.code === 'recent_reauthentication_required') {
      pendingMutation = reauthentication => action(reauthentication)
      Object.assign(dialog, { kind: 'reauthRetry', target: key, version: 0, title: t('重新认证后继续', 'Reauthenticate to continue'), description: t('短期认证已超过敏感操作窗口。确认用户在场后，只重试这一次被服务端拒绝的操作。', 'The short-lived authentication is outside the sensitive-action window. After confirming user presence, only this server-rejected action is retried.'), confirmLabel: t('认证并继续', 'Reauthenticate and continue'), phrase: '', sensitiveLabel: '' })
    } else error.value = message(cause)
    return false
  }
  finally { busy[key] = false }
}

function openCreate(): void { Object.assign(dialog, { kind: 'create', target: '', version: 0, title: t('连接渠道账户', 'Connect channel account'), description: t('此操作会发布新的渠道凭据，需要近期重新认证。', 'This publishes a new channel credential and requires recent reauthentication.'), confirmLabel: t('连接渠道', 'Connect channel'), phrase: '', sensitiveLabel: '' }) }
async function toggleAccount(account: ChannelAccountProjection): Promise<void> { await mutate(account.id, reauth => channelsOperationsApi.updateAccount(account.id, versionedMutation({ enabled: !account.enabled }, account.version), { reauthentication: reauth })) }
function openCredential(id: string, version: number): void { Object.assign(dialog, { kind: 'credential', target: id, version, title: t('轮换渠道凭据', 'Rotate channel credential'), description: t('新凭据只会发送一次，旧凭据将在原子发布后失效。', 'The new credential is sent once; the prior credential is replaced after atomic publication.'), confirmLabel: t('轮换', 'Rotate'), phrase: '', sensitiveLabel: t('新渠道凭据（仅写入）', 'New channel credential (write-only)') }) }
function openDelete(id: string): void { Object.assign(dialog, { kind: 'delete', target: id, version: 0, title: t('删除渠道账户', 'Delete channel account'), description: t('路由将被删除，凭据清理可能由后台继续完成。', 'Routes are removed and credential cleanup may continue in the background.'), confirmLabel: t('删除账户', 'Delete account'), phrase: id, sensitiveLabel: '' }) }
function openResend(delivery: DeliveryProjection): void { Object.assign(dialog, { kind: 'resend', target: delivery.id, version: 0, title: t('确认重复投递风险', 'Acknowledge duplicate delivery risk'), description: t('远端可能已经收到原消息。人工重发可能产生重复内容，并将写入审计记录。', 'The remote service may already have accepted the message. Manual resend can duplicate content and is audited.'), confirmLabel: t('承担风险并重发', 'Accept risk and resend'), phrase: delivery.id, sensitiveLabel: '' }) }
function openRoute(): void { Object.assign(dialog, { kind: 'route', target: routeDraft.account_id, version: 0, title: t('发布会话路由', 'Publish conversation route'), description: t('路由变更会改变后续消息使用的智能体，需要近期重新认证。', 'Route changes alter which agent receives future messages and require recent reauthentication.'), confirmLabel: t('保存路由', 'Save route'), phrase: '', sensitiveLabel: '' }) }
function openDeleteRoute(id: string): void { Object.assign(dialog, { kind: 'routeDelete', target: id, version: 0, title: t('移除会话路由', 'Remove conversation route'), description: t('后续消息将恢复到账户默认智能体。', 'Future messages will return to the account default agent.'), confirmLabel: t('移除路由', 'Remove route'), phrase: id, sensitiveLabel: '' }) }
function openRevealAudit(id: string): void { Object.assign(dialog, { kind: 'auditReveal', target: id, version: 0, title: t('临时揭示审计字段', 'Temporarily reveal audit fields'), description: t('仅请求非机密字段，结果只保存在内存并记录授权审计。', 'Only non-classified fields are requested; results stay in memory and the authorization is audited.'), confirmLabel: t('授权揭示', 'Authorize reveal'), phrase: '', sensitiveLabel: '' }) }
function closeDialog(): void { if (dialog.kind === 'reauthRetry') pendingMutation = null; Object.assign(dialog, { kind: '', target: '', version: 0, title: '', description: '', confirmLabel: '', phrase: '', sensitiveLabel: '' }); dialogError.value = '' }
async function confirmDialog(payload: { reauthentication: string; sensitiveValue: string }): Promise<void> {
  dialogBusy.value = true; dialogError.value = ''
  try {
    if (dialog.kind === 'reauthRetry') {
      if (!pendingMutation) throw new Error(t('待处理操作已失效', 'The pending operation expired'))
      await pendingMutation(payload.reauthentication)
      pendingMutation = null
    } else if (dialog.kind === 'credential') {
      await channelsOperationsApi.rotateCredential(dialog.target, { credential: payload.sensitiveValue, expected_version: dialog.version }, { reauthentication: payload.reauthentication })
    } else if (dialog.kind === 'create') {
      await channelsOperationsApi.createAccount({ ...accountDraft }, { reauthentication: payload.reauthentication })
      accountDraft.account_id = ''; accountDraft.credential = ''
    } else if (dialog.kind === 'route') {
      const { account_id, ...route } = routeDraft
      await channelsOperationsApi.putRoute(account_id, route, { reauthentication: payload.reauthentication })
    } else if (dialog.kind === 'routeDelete') {
      await channelsOperationsApi.deleteRoute(dialog.target, { reauthentication: payload.reauthentication })
    } else if (dialog.kind === 'auditReveal') {
      const auditId = dialog.target
      const result = await channelsOperationsApi.revealAudit(auditId, { fields: ['safe_count'], reason: 'operator inspection' }, { reauthentication: payload.reauthentication })
      revealedAudit[auditId] = JSON.stringify(result.revealed ?? {}, null, 2)
    } else if (dialog.kind === 'delete') await channelsOperationsApi.deleteAccount(dialog.target, { reauthentication: payload.reauthentication })
    else await channelsOperationsApi.resendOutbox(dialog.target, { reason: 'operator accepted duplicate risk', duplicate_risk_acknowledged: true, acknowledgement_version: '1' }, { reauthentication: payload.reauthentication })
    closeDialog(); await loadActive()
  } catch (cause) { dialogError.value = message(cause) }
  finally { dialogBusy.value = false }
}

async function loadMoreAccounts(): Promise<void> { if (busy.moreAccounts) return; busy.moreAccounts = true; try { const requestEpoch = epoch; const page = await channelsOperationsApi.listAccounts(nextCursor.value, controller?.signal); if (requestEpoch !== epoch || active.value !== 'accounts') return; accounts.value = [...accounts.value, ...page.items]; nextCursor.value = page.nextCursor } finally { busy.moreAccounts = false } }
async function loadMoreRecords(kind: 'inbox' | 'deliveries' | 'audit'): Promise<void> {
  const busyKey = kind === 'inbox' ? 'moreInbox' : kind === 'deliveries' ? 'moreDeliveries' : 'moreAudit'
  if (busy[busyKey]) return
  busy[busyKey] = true
  try {
  const requestEpoch = epoch
  const page = kind === 'inbox' ? await channelsOperationsApi.listInbox(inboxCursor.value, controller?.signal) : kind === 'deliveries' ? await channelsOperationsApi.listOutbox(deliveryCursor.value, controller?.signal) : await channelsOperationsApi.listAudit(auditCursor.value, controller?.signal)
  if (requestEpoch !== epoch || active.value !== kind) return
  if (kind === 'inbox') { inbox.value = [...inbox.value, ...page.items]; inboxCursor.value = page.nextCursor }
  else if (kind === 'deliveries') { deliveries.value = [...deliveries.value, ...page.items]; deliveryCursor.value = page.nextCursor }
  else { audit.value = [...audit.value, ...page.items]; auditCursor.value = page.nextCursor }
  } finally { busy[busyKey] = false }
}
async function saveRetention(): Promise<void> { await mutate('retention', reauth => channelsOperationsApi.setRetention(versionedMutation({ inbox_days: retention.inbox_days, outbox_days: retention.outbox_days, audit_days: retention.audit_days }, retention.version), { reauthentication: reauth })) }
async function runRetention(): Promise<void> { await mutate('retention', reauth => channelsOperationsApi.runRetention({ reauthentication: reauth })) }
async function requeueRetention(id: string): Promise<void> { await mutate(id, reauth => channelsOperationsApi.requeueRetention(id, { reauthentication: reauth })) }
watch(active, () => void loadActive())
watch(() => routeDraft.account_id, async id => {
  try { await loadRoutesForAccount(id) }
  catch (cause) { if (!(cause instanceof DOMException && cause.name === 'AbortError') && routeDraft.account_id === id) error.value = message(cause) }
})
onMounted(() => void loadActive())
onBeforeUnmount(() => { controller?.abort(); routeController?.abort(); pendingMutation = null; clearReveals(); accountDraft.credential = ''; closeDialog() })
</script>

<style scoped>
.operations-page { display: grid; gap: 18px; min-width: 0; color: var(--text-primary); }
.operations-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 22px; padding-bottom: 15px; border-bottom: 1px solid var(--border-color); }
.kicker { margin: 0 0 6px; color: #28736b; font: 700 11px/1.2 ui-monospace, SFMono-Regular, Consolas, monospace; letter-spacing: .09em; }
h3, h4 { margin: 0; letter-spacing: -.025em; } h3 { font-size: 21px; } h4 { font-size: 14px; }
.operations-header p:last-child, .resource-row p { margin: 6px 0 0; color: var(--text-muted); font-size: 12px; line-height: 1.5; }
.section-tabs { display: flex; gap: 4px; overflow-x: auto; padding: 3px; border: 1px solid var(--border-color); border-radius: 11px; }
.section-tabs button { flex: 0 0 auto; padding: 8px 11px; border: 0; border-radius: 8px; background: transparent; color: var(--text-secondary); cursor: pointer; font-size: 12px; }
.section-tabs button[aria-selected="true"] { background: #2d766e; color: white; }
button { font: inherit; } button:active:not(:disabled) { transform: translateY(1px); } button:disabled { cursor: not-allowed; opacity: .5; }
.quiet-button, .row-actions button, .resource-row > button, .inline-actions > button, .load-more, .state-panel button { min-height: 34px; padding: 0 11px; border: 1px solid var(--border-color); border-radius: 8px; background: transparent; color: var(--text-secondary); cursor: pointer; }
.content-grid { display: grid; grid-template-columns: minmax(245px, .74fr) minmax(300px, 1.26fr); gap: 22px; align-items: start; }
.editor-panel { display: grid; gap: 14px; padding: 17px; border: 1px solid var(--border-color); border-radius: 13px; background: color-mix(in srgb, var(--glass-bg-strong) 70%, transparent); }
label { display: grid; gap: 6px; color: var(--text-secondary); font-size: 12px; } input, select, textarea { width: 100%; min-width: 0; box-sizing: border-box; padding: 9px 10px; border: 1px solid var(--border-color); border-radius: 8px; background: var(--input-bg, rgba(255,255,255,.55)); color: var(--text-primary); } textarea { min-height: 78px; resize: vertical; } label small { color: var(--text-muted); line-height: 1.45; }
input:focus, select:focus, textarea:focus, button:focus-visible { outline: 2px solid color-mix(in srgb, #2d766e 45%, transparent); outline-offset: 2px; }
.primary-button { min-height: 38px; border: 0; border-radius: 8px; background: #2d766e; color: white; cursor: pointer; font-weight: 650; }
.list-panel { display: grid; gap: 0; min-width: 0; } .list-panel.full { border-top: 1px solid var(--border-color); }
.resource-row { display: flex; align-items: center; justify-content: space-between; gap: 16px; min-width: 0; padding: 14px 4px; border-bottom: 1px solid var(--border-color); }
.resource-row > div:first-child { min-width: 0; } .resource-row strong, .resource-row code { overflow-wrap: anywhere; font-size: 13px; } .resource-row code { color: var(--text-muted); }
.row-actions, .inline-actions { display: flex; flex-wrap: wrap; gap: 7px; } .danger-text { color: #b34b3c !important; }
.status-dot { display: inline-block; width: 7px; height: 7px; margin-right: 8px; border-radius: 50%; background: #8b929a; } .status-dot.active { background: #2d766e; }
.status-label { display: inline-block; margin: 0 8px 5px 0; padding: 3px 6px; border-radius: 5px; background: var(--hover-bg); color: var(--text-muted); font: 650 10px/1.2 ui-monospace, monospace; text-transform: uppercase; } .status-label.danger { background: #f7e3df; color: #a54134; } .status-label.warning { background: #f5ead1; color: #8a641e; }
.risk-critical { border-left: 3px solid #ad4939; padding-left: 11px; } .risk-high { border-left: 3px solid #b67b26; padding-left: 11px; }
.empty-state { display: grid; gap: 6px; place-items: start; padding: 38px 8px; color: var(--text-muted); font-size: 12px; } .empty-state strong { color: var(--text-primary); font-size: 14px; } .empty-state.compact { padding: 18px 0; }
.privacy-note { padding: 10px 12px; border-left: 3px solid #2d766e; background: color-mix(in srgb, #2d766e 8%, transparent); color: var(--text-secondary); font-size: 12px; }
pre { max-width: 100%; overflow: auto; padding: 8px; border-radius: 7px; background: var(--hover-bg); font-size: 11px; }
.skeleton-stack { display: grid; gap: 11px; } .skeleton-stack i { height: 62px; border-radius: 9px; background: linear-gradient(90deg, var(--hover-bg), color-mix(in srgb, var(--hover-bg) 40%, white), var(--hover-bg)); background-size: 200% 100%; animation: shimmer 1.3s ease infinite; }
.state-panel { display: grid; gap: 8px; padding: 18px; border: 1px solid var(--border-color); border-radius: 12px; } .state-panel.error { border-color: color-mix(in srgb, #b34b3c 45%, var(--border-color)); } .state-panel span { color: var(--text-muted); font-size: 12px; }
.screen-reader-live { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); }
@keyframes shimmer { to { background-position: -200% 0; } }
@media (max-width: 720px) { .operations-header, .resource-row { align-items: stretch; flex-direction: column; } .content-grid { grid-template-columns: minmax(0, 1fr); } .row-actions, .row-actions button, .resource-row > button { width: 100%; } .section-tabs { margin-inline: -2px; } }
@media (prefers-reduced-motion: reduce) { .skeleton-stack i { animation: none; } button { transition: none; } }
</style>
