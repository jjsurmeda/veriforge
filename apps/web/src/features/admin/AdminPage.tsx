import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import {
  Activity,
  BarChart3,
  Boxes,
  CheckCircle2,
  CreditCard,
  History,
  Library as LibraryIcon,
  Plus,
  RefreshCw,
  Save,
  Server,
  Settings2,
  ShieldCheck,
  Users,
} from 'lucide-react'

import {
  activateSettingsAdminSettingsVersionActivatePost,
  activeSettingsAdminSettingsGet,
  auditAdminAuditGet,
  createModelAdminModelsPost,
  createPlanAdminPlansPost,
  createProviderAdminProvidersPost,
  listRerankersRerankersGet,
  modelsAdminModelsGet,
  plansAdminPlansGet,
  providersAdminProvidersGet,
  rolesAdminRolesGet,
  settingsVersionsAdminSettingsVersionsGet,
  testProviderAdminProvidersProviderIdTestPost,
  updateModelAdminModelsModelIdPatch,
  updatePlanAdminPlansPlanIdPatch,
  updateProviderAdminProvidersProviderIdPatch,
  updateSettingsAdminSettingsPatch,
  updateUserAdminUsersUserIdPatch,
  upsertRoleAdminRolesPost,
  usersAdminUsersGet,
} from '../../generated/sdk.gen'
import type {
  AdminModelOut,
  AuditOut,
  ModelCreate,
  ModelPatch,
  PlanOut,
  PlanPatch,
  ProviderCreate,
  ProviderOut,
  ProviderPatch,
  RoleOut,
  SettingsOut,
  UserOut,
  UserPatch,
} from '../../generated/types.gen'
import { BenchmarksPanel } from './BenchmarksPanel'
import { DecisionLayerPanel } from './DecisionLayerPanel'
import { SharedLibraryPanel } from './SharedLibraryPanel'
import { useMe } from '../auth/hooks/useMe'
import { unwrap } from '../../lib/api'

type Section =
  | 'decisions'
  | 'providers'
  | 'models'
  | 'roles'
  | 'settings'
  | 'benchmarks'
  | 'library'
  | 'plans'
  | 'users'
  | 'audit'

function valueAt(data: Record<string, unknown>, path: string, fallback: number): number {
  const value = path.split('.').reduce<unknown>((current, key) => {
    if (typeof current !== 'object' || current === null) return undefined
    return (current as Record<string, unknown>)[key]
  }, data)
  return typeof value === 'number' ? value : fallback
}

function valueAtString(data: Record<string, unknown>, path: string, fallback: string): string {
  let node: unknown = data
  for (const key of path.split('.')) {
    if (typeof node !== 'object' || node === null) return fallback
    node = (node as Record<string, unknown>)[key]
  }
  return typeof node === 'string' ? node : fallback
}

function isDecisionModel(model: AdminModelOut): boolean {
  return model.capabilities?.decision === true
}

function Panel({ title, icon, children }: { title: string; icon?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="overflow-hidden rounded-xl border border-border bg-surface">
      <h2 className="flex items-center gap-2 border-b border-border bg-sidebar px-4 py-3 text-xs font-semibold text-fg">
        {icon ?? <Settings2 size={14} strokeWidth={1.75} className="text-fg" aria-hidden="true" />}
        {title}
      </h2>
      <div className="p-4 sm:p-5">{children}</div>
    </section>
  )
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5 text-xs text-fg-muted">
      <span className="text-xs font-medium text-fg">{label}</span>
      {children}
      {hint && <span className="text-2xs text-fg-muted">{hint}</span>}
    </label>
  )
}

function TableHeader({ left, right }: { left: string; right: string }) {
  return (
    <div className="mb-2 grid grid-cols-[minmax(0,1fr)_auto] gap-3 border-b border-border px-1 pb-2 text-2xs font-medium uppercase tracking-[0.1em] text-fg-muted">
      <span>{left}</span>
      <span>{right}</span>
    </div>
  )
}

function TableRow({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 border-b border-border/70 px-1 py-3 transition-colors duration-150 last:border-b-0 hover:bg-raised-hover ${className}`}>
      {children}
    </div>
  )
}

const inputClass =
  'h-9 min-w-0 rounded-lg border border-border bg-surface px-2.5 text-xs text-fg transition-[border-color,background-color] duration-150 hover:border-border-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring disabled:cursor-not-allowed disabled:opacity-50'
const buttonClass =
  'pressable inline-flex min-h-9 items-center justify-center gap-1.5 rounded-lg border border-border bg-raised px-2.5 text-xs font-medium text-fg hover:bg-raised-hover focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring disabled:cursor-not-allowed disabled:opacity-50'

/** A failed read is a visible failure with a retry, never an empty list
 *  (review P2): an operator must not read "provider list is empty" when the
 *  request actually failed. */
function QueryError({
  query,
  label,
}: {
  query: { isError: boolean; isFetching: boolean; refetch: () => unknown }
  label: string
}) {
  if (!query.isError) return null
  return (
    <div role="alert" className="mb-4 flex flex-wrap items-center gap-3 rounded-lg border border-border/30 bg-raised px-3 py-2 text-sm text-danger">
      <span>{label} could not be loaded.</span>
      <button
        type="button"
        className={buttonClass}
        disabled={query.isFetching}
        onClick={() => void query.refetch()}
      >
        <RefreshCw size={13} aria-hidden="true" />
        Retry
      </button>
    </div>
  )
}

export function AdminPage() {
  const me = useMe()
  const client = useQueryClient()
  const [section, setSection] = useState<Section>('settings')
  // null = keep whatever the active settings version says
  const [rerankerDraft, setRerankerDraft] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [providerForm, setProviderForm] = useState<ProviderCreate>({
    name: '',
    kind: 'openrouter',
    base_url: '',
    api_key: '',
  })
  const [planForm, setPlanForm] = useState({ name: '', credits_5h: 200000, credits_month: 2000000 })
  const [modelForm, setModelForm] = useState<ModelCreate>({
    provider_id: '',
    model_id: '',
    price_in: 0,
    price_out: 0,
    context_window: 128000,
  })
  const [settingsDraft, setSettingsDraft] = useState({
    top_k: 8,
    rrf_k: 60,
    rerank: true,
    hop_limit: 4,
    retry_limit: 2,
    deep_cap: 40000,
    threshold: 0.55,
    mode: 'auto',
    guardrails: true,
    injection_action: 'block',
    web_provider: 'tavily',
    source_priority: 'documents_first',
    trace_sample_rate: 1,
  })

  // Every admin read goes through unwrap: a failed request must reach
  // React Query as an error, never as an empty operator-visible list.
  const rerankers = useQuery({
    queryKey: ['rerankers'],
    queryFn: async () => unwrap(await listRerankersRerankersGet()),
  })
  const providers = useQuery({
    queryKey: ['admin', 'providers'],
    queryFn: async () => unwrap(await providersAdminProvidersGet()),
  })
  const models = useQuery({
    queryKey: ['admin', 'models'],
    queryFn: async () => unwrap(await modelsAdminModelsGet()),
  })
  const roles = useQuery({
    queryKey: ['admin', 'roles'],
    queryFn: async () => unwrap(await rolesAdminRolesGet()),
  })
  const settings = useQuery({
    queryKey: ['admin', 'settings'],
    queryFn: async () => unwrap(await activeSettingsAdminSettingsGet()),
  })
  const versions = useQuery({
    queryKey: ['admin', 'settings', 'versions'],
    queryFn: async () => unwrap(await settingsVersionsAdminSettingsVersionsGet()),
  })
  const plans = useQuery({
    queryKey: ['admin', 'plans'],
    queryFn: async () => unwrap(await plansAdminPlansGet()),
  })
  const users = useQuery({
    queryKey: ['admin', 'users'],
    queryFn: async () => unwrap(await usersAdminUsersGet()),
  })
  const audit = useQuery({
    queryKey: ['admin', 'audit'],
    queryFn: async () => unwrap(await auditAdminAuditGet()),
  })

  const invalidate = (keys: string[][]) => {
    for (const key of keys) void client.invalidateQueries({ queryKey: key })
  }
  const providerCreate = useMutation({
    mutationFn: async (body: ProviderCreate) => {
      const { data, error } = await createProviderAdminProvidersPost({ body })
      if (error) throw error
      return data
    },
    onSuccess: () => {
      setNotice('Provider saved with its key encrypted.')
      invalidate([['admin', 'providers']])
    },
  })
  const providerUpdate = useMutation({
    mutationFn: async ({ id, body }: { id: string; body: ProviderPatch }) => {
      const { data, error } = await updateProviderAdminProvidersProviderIdPatch({
        path: { provider_id: id },
        body,
      })
      if (error) throw error
      return data
    },
    onSuccess: () => invalidate([['admin', 'providers']]),
  })
  const providerTest = useMutation({
    mutationFn: async (id: string) => {
      const { error } = await testProviderAdminProvidersProviderIdTestPost({
        path: { provider_id: id },
      })
      if (error) throw error
      setNotice('Provider responded successfully.')
    },
  })
  const modelCreate = useMutation({
    mutationFn: async (body: ModelCreate) => {
      const { data, error } = await createModelAdminModelsPost({ body })
      if (error) throw error
      return data
    },
    onSuccess: () => {
      setNotice('Model added to the catalogue.')
      invalidate([['admin', 'models']])
    },
  })
  const modelUpdate = useMutation({
    mutationFn: async ({ id, body }: { id: string; body: ModelPatch }) => {
      const { data, error } = await updateModelAdminModelsModelIdPatch({
        path: { model_id: id },
        body,
      })
      if (error) throw error
      return data
    },
    onSuccess: () => invalidate([['admin', 'models']]),
  })
  const roleSave = useMutation({
    mutationFn: async (body: { role: string; model_id: string; fallback_model_id?: string }) => {
      const { data, error } = await upsertRoleAdminRolesPost({ body })
      if (error) throw error
      return data
    },
    onSuccess: () => {
      setNotice('Model role saved. New runs will use it.')
      invalidate([['admin', 'roles']])
    },
  })
  const settingsSave = useMutation({
    mutationFn: async () => {
      const { data, error } = await updateSettingsAdminSettingsPatch({
        body: {
          retrieval: {
            top_k: settingsDraft.top_k,
            rrf_k: settingsDraft.rrf_k,
            rerank: settingsDraft.rerank,
            ...(rerankerDraft ? { reranker: rerankerDraft } : {}),
            hop_limit: settingsDraft.hop_limit,
            retry_limit: settingsDraft.retry_limit,
          },
          deep: { per_run_credit_cap: settingsDraft.deep_cap },
          thresholds: {
            evidence_floor: {
              jev: settingsDraft.threshold,
              fallback: settingsDraft.threshold,
            },
          },
          guardrails: {
            enabled: settingsDraft.guardrails,
            actions: { injection: settingsDraft.injection_action },
          },
          web_search_provider: settingsDraft.web_provider,
          source_priority: settingsDraft.source_priority,
          trace_sample_rate: settingsDraft.trace_sample_rate,
          decision_engine_mode: settingsDraft.mode,
        },
      })
      if (error) throw error
      return data
    },
    onSuccess: () => {
      setNotice('Settings version created. Rollback is available in Versions.')
      invalidate([['admin', 'settings'], ['admin', 'settings', 'versions'], ['admin', 'audit']])
    },
  })
  const rollback = useMutation({
    mutationFn: async (version: number) => {
      const { data, error } = await activateSettingsAdminSettingsVersionActivatePost({
        path: { version },
      })
      if (error) throw error
      return data
    },
    onSuccess: () => {
      setNotice('Settings version activated.')
      invalidate([['admin', 'settings'], ['admin', 'settings', 'versions'], ['admin', 'audit']])
    },
  })
  const planCreate = useMutation({
    mutationFn: async () => {
      const { data, error } = await createPlanAdminPlansPost({ body: planForm })
      if (error) throw error
      return data
    },
    onSuccess: () => {
      setNotice('Plan created.')
      invalidate([['admin', 'plans']])
    },
  })
  const planUpdate = useMutation({
    mutationFn: async ({ id, body }: { id: string; body: PlanPatch }) => {
      const { data, error } = await updatePlanAdminPlansPlanIdPatch({ path: { plan_id: id }, body })
      if (error) throw error
      return data
    },
    onSuccess: () => invalidate([['admin', 'plans']]),
  })
  const userUpdate = useMutation({
    mutationFn: async ({ id, body }: { id: string; body: UserPatch }) => {
      const { data, error } = await updateUserAdminUsersUserIdPatch({ path: { user_id: id }, body })
      if (error) throw error
      return data
    },
    onSuccess: () => invalidate([['admin', 'users']]),
  })

  if (me.isLoading) return <main className="min-h-screen bg-main p-8 text-fg">Loading admin…</main>
  if (me.data?.role !== 'admin') {
    return (
      <main className="min-h-screen bg-main p-8 text-fg">
        <h1 className="text-lg font-semibold">Administrator access required.</h1>
        <p className="mt-2 text-sm text-fg-muted">This area is for administrators. Your chats and the Decision layer page are still available.</p>
        <a href="/" className="mt-4 inline-flex min-h-9 items-center rounded-lg border border-border bg-raised px-3 text-xs font-medium text-fg hover:bg-raised-hover focus-visible:outline-2 focus-visible:outline-focus-ring">Back to chats</a>
      </main>
    )
  }

  const current = settings.data
  const data = (current?.data ?? {}) as Record<string, unknown>
  const currentTopK = valueAt(data, 'retrieval.top_k', settingsDraft.top_k)
  const currentThreshold = valueAt(data, 'thresholds.evidence_floor.jev', settingsDraft.threshold)
  const currentReranker = valueAtString(data, 'retrieval.reranker', 'jev')
  const selectedReranker = rerankerDraft ?? currentReranker
  const rerankerInfo = (rerankers.data ?? []).find((r) => r.id === selectedReranker)
  const currentMode = typeof data.decision_engine_mode === 'string' ? data.decision_engine_mode : settingsDraft.mode
  const tabs: Array<[Section, string, React.ReactNode]> = [
    ['decisions', 'Decision layer', <Activity key="decisions" size={14} aria-hidden="true" />],
    ['settings', 'Settings', <Settings2 key="settings" size={14} aria-hidden="true" />],
    ['providers', 'Providers', <Server key="providers" size={14} aria-hidden="true" />],
    ['models', 'Models', <Boxes key="models" size={14} aria-hidden="true" />],
    ['roles', 'Roles', <ShieldCheck key="roles" size={14} aria-hidden="true" />],
    ['library', 'Shared library', <LibraryIcon key="library" size={14} aria-hidden="true" />],
    ['benchmarks', 'Benchmarks', <BarChart3 key="benchmarks" size={14} aria-hidden="true" />],
    ['plans', 'Plans', <CreditCard key="plans" size={14} aria-hidden="true" />],
    ['users', 'Users', <Users key="users" size={14} aria-hidden="true" />],
    ['audit', 'Audit', <History key="audit" size={14} aria-hidden="true" />],
  ]

  return (
    <main className="h-full overflow-y-auto bg-main text-fg">
      <header className="border-b border-border bg-sidebar px-5 py-4 sm:px-8">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <span className="flex size-9 items-center justify-center rounded-lg border border-border bg-surface text-fg">
              <ShieldCheck size={18} strokeWidth={1.75} aria-hidden="true" />
            </span>
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-fg">Administration</p>
              <h1 className="mt-1 text-2xl font-semibold tracking-tight text-fg">System control room</h1>
            </div>
          </div>
        </div>
      </header>
      <div className="mx-auto grid max-w-7xl gap-5 p-5 sm:p-8 lg:grid-cols-[13rem_minmax(0,1fr)] lg:gap-8">
        <label className="flex flex-col gap-1.5 text-xs text-fg-muted lg:hidden">
          <span className="font-medium text-fg">Section</span>
          <select className={inputClass} value={section} onChange={(e) => setSection(e.target.value as Section)}>
            {tabs.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
          </select>
        </label>
        <nav className="hidden gap-1 rounded-xl border border-border bg-surface p-1 lg:sticky lg:top-5 lg:flex lg:flex-col lg:self-start" aria-label="Admin sections">
          {tabs.map(([id, label, icon]) => (
            <button
              key={id}
              type="button"
              onClick={() => setSection(id)}
              className={`inline-flex min-h-10 items-center gap-2 whitespace-nowrap rounded-lg px-3 py-2 text-left text-xs font-medium transition-[background-color,color] duration-150 focus-visible:outline-2 focus-visible:outline-focus-ring ${
                section === id ? 'bg-raised text-fg' : 'text-fg-muted hover:bg-raised-hover hover:text-fg'
              }`}
            >
              {icon}
              {label}
            </button>
          ))}
        </nav>
        <div className="min-w-0 space-y-4">
          {notice && <p role="status" className="flex items-center gap-2 rounded-lg border border-border/30 bg-raised px-3 py-2 text-sm text-success"><CheckCircle2 size={15} aria-hidden="true" />{notice}</p>}
          {(
            [
              ['Providers', providers],
              ['Models', models],
              ['Roles', roles],
              ['Settings', settings],
              ['Settings versions', versions],
              ['Plans', plans],
              ['Users', users],
              ['Audit log', audit],
            ] as const
          ).map(([label, query]) => (
            <QueryError key={label} label={label} query={query} />
          ))}
          {section === 'decisions' && <DecisionLayerPanel admin />}
          {section === 'benchmarks' && <BenchmarksPanel />}
          {section === 'settings' && (
            <>
              <Panel title="Runtime settings" icon={<Settings2 size={14} strokeWidth={1.75} aria-hidden="true" />}>
                <div className="grid gap-3 sm:grid-cols-3">
                  <Field label="Retrieval top-k">
                    <input className={inputClass} type="number" min={1} value={settingsDraft.top_k} onChange={(e) => setSettingsDraft({ ...settingsDraft, top_k: Number(e.target.value) })} />
                  </Field>
                  <Field label="Gate floor (mean top-3)">
                    <input className={inputClass} type="number" min={0} max={1} step="0.01" value={settingsDraft.threshold} onChange={(e) => setSettingsDraft({ ...settingsDraft, threshold: Number(e.target.value) })} />
                  </Field>
                  <Field label="Decision engine">
                    <select className={inputClass} value={settingsDraft.mode} onChange={(e) => setSettingsDraft({ ...settingsDraft, mode: e.target.value })}>
                      <option value="auto">Auto</option>
                      <option value="jev_only">Jev only</option>
                      <option value="fallback_only">Fallback only</option>
                    </select>
                  </Field>
                </div>
                <div className="mt-3 grid gap-3 sm:grid-cols-4">
                  <Field label="Fusion constant"><input className={inputClass} type="number" min={1} value={settingsDraft.rrf_k} onChange={(e) => setSettingsDraft({ ...settingsDraft, rrf_k: Number(e.target.value) })} /></Field>
                  <Field label="Rerank"><select className={inputClass} value={settingsDraft.rerank ? 'on' : 'off'} onChange={(e) => setSettingsDraft({ ...settingsDraft, rerank: e.target.value === 'on' })}><option value="on">On</option><option value="off">Off</option></select></Field>
                  <Field label="Reranker" hint={rerankerInfo ? `${rerankerInfo.kind}${rerankerInfo.calibrated ? ', calibrated' : ', not calibrated'}${rerankerInfo.cost_per_1k_queries_usd === null ? '' : `, $${rerankerInfo.cost_per_1k_queries_usd}/1k queries`}${rerankerInfo.is_default ? ', default' : ''}${rerankerInfo.key_present ? '' : ', no API key'}` : 'Loading rerankers'}>
                    <select aria-label="Reranker" className={inputClass} value={selectedReranker} onChange={(e) => setRerankerDraft(e.target.value)} disabled={!rerankers.data}>
                      {(rerankers.data ?? [{ id: selectedReranker, label: selectedReranker }]).map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
                    </select>
                  </Field>
                  <Field label="Hop limit"><input className={inputClass} type="number" min={1} max={4} value={settingsDraft.hop_limit} onChange={(e) => setSettingsDraft({ ...settingsDraft, hop_limit: Number(e.target.value) })} /></Field>
                  <Field label="Retry limit"><input className={inputClass} type="number" min={0} value={settingsDraft.retry_limit} onChange={(e) => setSettingsDraft({ ...settingsDraft, retry_limit: Number(e.target.value) })} /></Field>
                  <Field label="Deep credit cap"><input className={inputClass} type="number" min={1} value={settingsDraft.deep_cap} onChange={(e) => setSettingsDraft({ ...settingsDraft, deep_cap: Number(e.target.value) })} /></Field>
                  <Field label="Guardrails"><select className={inputClass} value={settingsDraft.guardrails ? 'on' : 'off'} onChange={(e) => setSettingsDraft({ ...settingsDraft, guardrails: e.target.value === 'on' })}><option value="on">Enabled</option><option value="off">Disabled</option></select></Field>
                  <Field label="Injection action"><select className={inputClass} value={settingsDraft.injection_action} onChange={(e) => setSettingsDraft({ ...settingsDraft, injection_action: e.target.value })}><option value="block">Block</option><option value="warn">Warn</option><option value="off">Off</option></select></Field>
                  <Field label="Web provider"><select className={inputClass} value={settingsDraft.web_provider} onChange={(e) => setSettingsDraft({ ...settingsDraft, web_provider: e.target.value })}><option value="tavily">Tavily</option><option value="brave">Brave</option></select></Field>
                  <Field label="Source priority"><select className={inputClass} value={settingsDraft.source_priority} onChange={(e) => setSettingsDraft({ ...settingsDraft, source_priority: e.target.value })}><option value="documents_first">Documents first</option><option value="web_first">Web first</option></select></Field>
                  <Field label="Trace sample rate"><input className={inputClass} type="number" min={0} max={1} step="0.01" value={settingsDraft.trace_sample_rate} onChange={(e) => setSettingsDraft({ ...settingsDraft, trace_sample_rate: Number(e.target.value) })} /></Field>
                </div>
                <p className="mt-3 font-mono text-2xs text-fg-muted">Active v{current?.version ?? '—'} · reranker {currentReranker} · top-k {currentTopK} · threshold {currentThreshold} · {currentMode}</p>
                 <button type="button" className={`${buttonClass} mt-4`} onClick={() => settingsSave.mutate()} disabled={settingsSave.isPending}><Save size={13} aria-hidden="true" />Create version</button>

              </Panel>
              <Panel title="Versions / rollback" icon={<RefreshCw size={14} strokeWidth={1.75} aria-hidden="true" />}>
                <div className="divide-y divide-border">
                  {(versions.data ?? []).map((version: SettingsOut) => (
                     <div key={version.version} className="flex items-center justify-between gap-3 border-b border-border/70 px-1 py-2.5 last:border-b-0">
                       <div className="flex items-baseline gap-2"><span className="font-mono text-sm text-fg">v{version.version}</span><span className="text-xs text-fg-muted">{version.active ? 'active' : 'inactive'}</span></div>
                        {!version.active && <button type="button" className={buttonClass} onClick={() => rollback.mutate(version.version)} disabled={rollback.isPending}><RefreshCw size={13} aria-hidden="true" />Activate</button>}

                     </div>
                  ))}
                </div>
              </Panel>
            </>
          )}
          {section === 'providers' && (
            <Panel title="Providers" icon={<Server size={14} strokeWidth={1.75} aria-hidden="true" />}>
              <div className="grid gap-3 sm:grid-cols-4">
                <Field label="Name"><input className={inputClass} value={providerForm.name} onChange={(e) => setProviderForm({ ...providerForm, name: e.target.value })} /></Field>
                <Field label="Kind"><input className={inputClass} value={providerForm.kind} onChange={(e) => setProviderForm({ ...providerForm, kind: e.target.value })} /></Field>
                <Field label="Base URL"><input className={inputClass} value={providerForm.base_url ?? ''} onChange={(e) => setProviderForm({ ...providerForm, base_url: e.target.value })} /></Field>
                <Field label="API key"><input className={inputClass} type="password" value={providerForm.api_key ?? ''} onChange={(e) => setProviderForm({ ...providerForm, api_key: e.target.value })} /></Field>
              </div>
               <button type="button" className={`${buttonClass} mt-4`} onClick={() => providerCreate.mutate(providerForm)} disabled={providerCreate.isPending}><Plus size={13} aria-hidden="true" />Add provider</button>

               <div className="mt-5 border-t border-border/70 pt-3">
                 <TableHeader left="Provider / status" right="Actions" />
                 {(providers.data ?? []).map((provider: ProviderOut) => (
                   <TableRow key={provider.id}>
                     <div className="min-w-0">
                       <div className="truncate font-mono text-sm text-fg">{provider.name}</div>
                       <div className="mt-0.5 truncate text-xs text-fg-muted">
                         {provider.kind} · {provider.enabled ? 'enabled' : 'disabled'} · key {provider.has_api_key ? 'stored' : 'missing'}
                       </div>
                     </div>
                     <div className="flex gap-2">
                        <button type="button" className={buttonClass} onClick={() => providerTest.mutate(provider.id)}><CheckCircle2 size={13} aria-hidden="true" />Test</button>

                       <button type="button" className={buttonClass} onClick={() => providerUpdate.mutate({ id: provider.id, body: { enabled: !provider.enabled } })}>{provider.enabled ? 'Disable' : 'Enable'}</button>
                     </div>
                   </TableRow>
                 ))}
               </div>
            </Panel>
          )}
          {section === 'models' && (
            <Panel title="Model catalogue" icon={<Boxes size={14} strokeWidth={1.75} aria-hidden="true" />}>
              <div className="grid gap-3 sm:grid-cols-3">
                <Field label="Provider"><select className={inputClass} value={modelForm.provider_id} onChange={(e) => setModelForm({ ...modelForm, provider_id: e.target.value })}><option value="">Select provider</option>{(providers.data ?? []).map((provider: ProviderOut) => <option key={provider.id} value={provider.id}>{provider.name}</option>)}</select></Field>
                <Field label="Model ID" hint="Provider model slug, for example vendor/model-name."><input className={inputClass} placeholder="vendor/model-name" value={modelForm.model_id} onChange={(e) => setModelForm({ ...modelForm, model_id: e.target.value })} /></Field>
                <Field label="Context window" hint="Maximum tokens the model accepts."><input className={inputClass} type="number" value={modelForm.context_window ?? ''} onChange={(e) => setModelForm({ ...modelForm, context_window: Number(e.target.value) })} /></Field>
                <Field label="Input price" hint="Per token; turns usage into credits. 0 means free."><input className={inputClass} type="number" step="0.000001" value={modelForm.price_in ?? ''} onChange={(e) => setModelForm({ ...modelForm, price_in: Number(e.target.value) })} /></Field>
                <Field label="Output price" hint="Per token; turns usage into credits. 0 means free."><input className={inputClass} type="number" step="0.000001" value={modelForm.price_out ?? ''} onChange={(e) => setModelForm({ ...modelForm, price_out: Number(e.target.value) })} /></Field>
              </div>
               <button type="button" className={`${buttonClass} mt-4`} onClick={() => modelCreate.mutate(modelForm)} disabled={modelCreate.isPending || !modelForm.provider_id || !modelForm.model_id}><Plus size={13} aria-hidden="true" />Add model</button>
               {(!modelForm.provider_id || !modelForm.model_id) && <p className="mt-2 text-2xs text-fg-muted">Choose a provider and enter a model ID to add a model.</p>}

               <div className="mt-5 border-t border-border/70 pt-3">
                 <TableHeader left="Model / limits" right="Actions" />
                 {(models.data ?? []).map((model: AdminModelOut) => (
                   <TableRow key={model.id}>
                     <div className="min-w-0">
                       <div className="truncate font-mono text-sm text-fg">{model.model_id}{isDecisionModel(model) && <span className="ml-2 rounded border border-border px-1.5 py-0.5 font-sans text-2xs text-fg-muted">decision</span>}</div>
                       <div className="mt-0.5 text-xs text-fg-muted">
                         {model.context_window ?? '—'} tokens · in {model.price_in ?? '—'} / out {model.price_out ?? '—'}
                       </div>
                     </div>
                     <button type="button" className={buttonClass} onClick={() => modelUpdate.mutate({ id: model.id, body: { enabled: !model.enabled } })}>{model.enabled ? 'Disable' : 'Enable'}</button>
                   </TableRow>
                 ))}
               </div>
            </Panel>
          )}
          {section === 'roles' && (
             <Panel title="Model roles" icon={<ShieldCheck size={14} strokeWidth={1.75} aria-hidden="true" />}>
               <div className="border-t border-border/70 pt-3">
                 <TableHeader left="Role" right="Assigned model" />
                 {(roles.data ?? []).map((role: RoleOut) => (
                   <TableRow key={role.role}>
                     <span className="min-w-0 truncate font-mono text-sm text-fg">{role.role}</span>
                     <select aria-label={`${role.role} model`} className={inputClass} value={role.model_id} onChange={(e) => roleSave.mutate({ role: role.role, model_id: e.target.value, fallback_model_id: role.fallback_model_id ?? undefined })}>
                       {(models.data ?? []).map((model: AdminModelOut) => <option key={model.id} value={model.model_id}>{model.model_id}</option>)}
                     </select>
                   </TableRow>
                 ))}
               </div>
             </Panel>
          )}
          {section === 'plans' && (
            <Panel title="Plans and quota overrides" icon={<CreditCard size={14} strokeWidth={1.75} aria-hidden="true" />}>
              <div className="grid gap-3 sm:grid-cols-3"><Field label="Name"><input className={inputClass} value={planForm.name} onChange={(e) => setPlanForm({ ...planForm, name: e.target.value })} /></Field><Field label="5h credits"><input className={inputClass} type="number" value={planForm.credits_5h} onChange={(e) => setPlanForm({ ...planForm, credits_5h: Number(e.target.value) })} /></Field><Field label="Monthly credits"><input className={inputClass} type="number" value={planForm.credits_month} onChange={(e) => setPlanForm({ ...planForm, credits_month: Number(e.target.value) })} /></Field></div>
               <button type="button" className={`${buttonClass} mt-4`} onClick={() => planCreate.mutate()} disabled={planCreate.isPending}><Plus size={13} aria-hidden="true" />Add plan</button>

               <div className="mt-5 border-t border-border/70 pt-3">
                 <TableHeader left="Plan / 5h credits" right="Monthly / action" />
                 {(plans.data ?? []).map((plan: PlanOut) => <PlanRow key={plan.id} plan={plan} onSave={(body) => planUpdate.mutate({ id: plan.id, body })} />)}
               </div>
            </Panel>
          )}
          {section === 'library' && (
            <Panel title="Shared library" icon={<LibraryIcon size={14} strokeWidth={1.75} aria-hidden="true" />}>
              <SharedLibraryPanel />
            </Panel>
          )}
          {section === 'users' && (
             <Panel title="Users" icon={<Users size={14} strokeWidth={1.75} aria-hidden="true" />}>
               <div className="border-t border-border/70 pt-3">
                 <TableHeader left="User / role" right="Overrides" />
                 {(users.data ?? []).map((user: UserOut) => <UserRow key={user.id} user={user} onUpdate={(body) => userUpdate.mutate({ id: user.id, body })} />)}
               </div>
             </Panel>
          )}
          {section === 'audit' && (
             <Panel title="Audit log" icon={<History size={14} strokeWidth={1.75} aria-hidden="true" />}>
               <div className="border-t border-border/70 pt-3">
                 <TableHeader left="Action / target" right="Time" />
                 {(audit.data ?? []).map((row: AuditOut) => (
                   <TableRow key={row.id}>
                     <div className="min-w-0">
                       <div className="truncate font-mono text-sm text-fg">{row.action}</div>
                       <div className="mt-0.5 truncate text-xs text-fg-muted">{row.target}</div>
                     </div>
                     <span className="shrink-0 text-xs text-fg-muted">{new Date(row.created_at).toLocaleString()}</span>
                   </TableRow>
                 ))}
               </div>
             </Panel>
          )}
        </div>
      </div>
    </main>
  )
}

function UserRow({ user, onUpdate }: { user: UserOut; onUpdate: (body: UserPatch) => void }) {
  const [fiveHour, setFiveHour] = useState(user.credits_5h ?? 0)
  const [monthly, setMonthly] = useState(user.credits_month ?? 0)
  return (
    <TableRow>
      <div className="min-w-0">
        <div className="truncate text-sm text-fg">{user.email}</div>
        <div className="mt-0.5 text-xs text-fg-muted">{user.role} · {user.status}</div>
      </div>
      <div className="flex flex-wrap items-center justify-end gap-2">
        <input aria-label={`${user.email} 5h override`} className={inputClass} type="number" min={0} value={fiveHour} onChange={(e) => setFiveHour(Number(e.target.value))} />
        <input aria-label={`${user.email} monthly override`} className={inputClass} type="number" min={0} value={monthly} onChange={(e) => setMonthly(Number(e.target.value))} />
         <button type="button" className={buttonClass} onClick={() => onUpdate({ credits_5h: fiveHour, credits_month: monthly })}><Save size={13} aria-hidden="true" />Save quota</button>

        <select aria-label={`${user.email} role`} className={inputClass} value={user.role} onChange={(e) => onUpdate({ role: e.target.value as UserPatch['role'] })}><option value="user">user</option><option value="admin">admin</option><option value="demo">demo</option></select>
        <button type="button" className={buttonClass} onClick={() => onUpdate({ status: user.status === 'active' ? 'disabled' : 'active' })}>{user.status === 'active' ? 'Disable' : 'Enable'}</button>
      </div>
    </TableRow>
  )
}

function PlanRow({ plan, onSave }: { plan: PlanOut; onSave: (body: PlanPatch) => void }) {
  const [month, setMonth] = useState(plan.credits_month)
  return (
    <TableRow>
      <div className="min-w-0">
        <div className="truncate font-mono text-sm text-fg">{plan.name}</div>
        <div className="mt-0.5 text-xs text-fg-muted">5h {plan.credits_5h}</div>
      </div>
      <div className="flex items-center gap-2">
        <input aria-label={`${plan.name} monthly credits`} className={inputClass} type="number" value={month} onChange={(e) => setMonth(Number(e.target.value))} />
         <button type="button" className={buttonClass} onClick={() => onSave({ credits_month: month })}><Save size={13} aria-hidden="true" />Save</button>

      </div>
    </TableRow>
  )
}
