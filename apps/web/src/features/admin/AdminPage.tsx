import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import {
  Boxes,
  CheckCircle2,
  CreditCard,
  History,
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
import { useMe } from '../auth/hooks/useMe'

type Section = 'providers' | 'models' | 'roles' | 'settings' | 'plans' | 'users' | 'audit'

function valueAt(data: Record<string, unknown>, path: string, fallback: number): number {
  const value = path.split('.').reduce<unknown>((current, key) => {
    if (typeof current !== 'object' || current === null) return undefined
    return (current as Record<string, unknown>)[key]
  }, data)
  return typeof value === 'number' ? value : fallback
}

function isDecisionModel(model: AdminModelOut): boolean {
  return model.capabilities?.decision === true
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="overflow-hidden rounded-xl border border-border bg-surface shadow-sm">
      <h2 className="flex items-center gap-2 border-b border-border bg-surface-muted/60 px-4 py-3 font-mono text-[0.65rem] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
        <Settings2 size={13} className="text-primary" aria-hidden="true" />
        {title}
      </h2>
      <div className="p-4 sm:p-5">{children}</div>
    </section>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5 text-xs text-muted-foreground">
      <span className="font-mono text-[0.65rem] uppercase tracking-[0.08em] text-muted-foreground/80">{label}</span>
      {children}
    </label>
  )
}

function TableHeader({ left, right }: { left: string; right: string }) {
  return (
    <div className="mb-2 grid grid-cols-[minmax(0,1fr)_auto] gap-3 border-b border-border px-1 pb-2 font-mono text-[0.65rem] uppercase tracking-[0.1em] text-muted-foreground">
      <span>{left}</span>
      <span>{right}</span>
    </div>
  )
}

function TableRow({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 border-b border-border/70 px-1 py-2.5 transition-colors duration-180 last:border-b-0 hover:bg-surface-muted ${className}`}>
      {children}
    </div>
  )
}

const inputClass =
  'h-9 min-w-0 rounded-lg border border-border bg-background px-2.5 text-xs text-foreground transition-[border-color,box-shadow] duration-180 hover:border-primary/40 focus-visible:border-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/25 disabled:cursor-not-allowed disabled:opacity-50 motion-reduce:transition-none'
const buttonClass =
  'inline-flex min-h-8 items-center justify-center gap-1.5 rounded-lg border border-border bg-surface-muted px-2.5 py-1.5 text-xs font-medium text-foreground transition-[color,background-color,border-color,transform,box-shadow] duration-180 hover:-translate-y-px hover:border-primary/40 hover:bg-primary-soft hover:shadow-sm active:translate-y-0 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:cursor-not-allowed disabled:opacity-50 motion-reduce:transform-none motion-reduce:transition-none'

export function AdminPage() {
  const me = useMe()
  const client = useQueryClient()
  const [section, setSection] = useState<Section>('settings')
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
    threshold: 0.6,
    abstain_threshold: 0.35,
    mode: 'auto',
    guardrails: true,
    injection_action: 'block',
    web_provider: 'tavily',
    source_priority: 'documents_first',
    trace_sample_rate: 1,
  })

  const providers = useQuery({
    queryKey: ['admin', 'providers'],
    queryFn: async () => (await providersAdminProvidersGet()).data ?? [],
  })
  const models = useQuery({
    queryKey: ['admin', 'models'],
    queryFn: async () => (await modelsAdminModelsGet()).data ?? [],
  })
  const roles = useQuery({
    queryKey: ['admin', 'roles'],
    queryFn: async () => (await rolesAdminRolesGet()).data ?? [],
  })
  const settings = useQuery({
    queryKey: ['admin', 'settings'],
    queryFn: async () => (await activeSettingsAdminSettingsGet()).data,
  })
  const versions = useQuery({
    queryKey: ['admin', 'settings', 'versions'],
    queryFn: async () => (await settingsVersionsAdminSettingsVersionsGet()).data ?? [],
  })
  const plans = useQuery({
    queryKey: ['admin', 'plans'],
    queryFn: async () => (await plansAdminPlansGet()).data ?? [],
  })
  const users = useQuery({
    queryKey: ['admin', 'users'],
    queryFn: async () => (await usersAdminUsersGet()).data ?? [],
  })
  const audit = useQuery({
    queryKey: ['admin', 'audit'],
    queryFn: async () => (await auditAdminAuditGet()).data ?? [],
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
            hop_limit: settingsDraft.hop_limit,
            retry_limit: settingsDraft.retry_limit,
          },
          deep: { per_run_credit_cap: settingsDraft.deep_cap },
          thresholds: {
            sufficient_retry: { jev: settingsDraft.threshold, fallback: settingsDraft.threshold },
            sufficient_abstain: {
              jev: settingsDraft.abstain_threshold,
              fallback: settingsDraft.abstain_threshold,
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

  if (me.isLoading) return <main className="min-h-screen bg-background p-8 text-foreground">Loading admin…</main>
  if (me.data?.role !== 'admin') {
    return <main className="min-h-screen bg-background p-8 text-foreground">Administrator access required.</main>
  }

  const current = settings.data
  const data = (current?.data ?? {}) as Record<string, unknown>
  const currentTopK = valueAt(data, 'retrieval.top_k', settingsDraft.top_k)
  const currentThreshold = valueAt(data, 'thresholds.sufficient_retry.jev', settingsDraft.threshold)
  const currentMode = typeof data.decision_engine_mode === 'string' ? data.decision_engine_mode : settingsDraft.mode
  const tabs: Array<[Section, string, React.ReactNode]> = [
    ['settings', 'Settings', <Settings2 key="settings" size={14} aria-hidden="true" />],
    ['providers', 'Providers', <Server key="providers" size={14} aria-hidden="true" />],
    ['models', 'Models', <Boxes key="models" size={14} aria-hidden="true" />],
    ['roles', 'Roles', <ShieldCheck key="roles" size={14} aria-hidden="true" />],
    ['plans', 'Plans', <CreditCard key="plans" size={14} aria-hidden="true" />],
    ['users', 'Users', <Users key="users" size={14} aria-hidden="true" />],
    ['audit', 'Audit', <History key="audit" size={14} aria-hidden="true" />],
  ]

  return (
    <main className="h-full overflow-y-auto bg-background text-foreground">
      <header className="border-b border-border bg-surface px-5 py-4 shadow-sm sm:px-8">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <span className="flex size-10 items-center justify-center rounded-xl bg-primary-soft text-primary shadow-sm">
              <ShieldCheck size={19} aria-hidden="true" />
            </span>
            <div>
               <p className="font-mono text-xs font-semibold uppercase tracking-[0.16em] text-primary">Administration</p>
              <h1 className="mt-1 font-display text-2xl font-semibold tracking-tight text-foreground">System control room</h1>
            </div>
          </div>
        </div>
      </header>
      <div className="mx-auto grid max-w-7xl gap-5 p-5 sm:p-8 lg:grid-cols-[13rem_minmax(0,1fr)] lg:gap-8">
        <nav className="flex gap-1 overflow-x-auto rounded-xl border border-border bg-surface p-1 shadow-sm lg:sticky lg:top-5 lg:flex-col lg:self-start" aria-label="Admin sections">
          {tabs.map(([id, label, icon]) => (
            <button
              key={id}
              type="button"
              onClick={() => setSection(id)}
              className={`inline-flex min-h-10 items-center gap-2 whitespace-nowrap rounded-lg px-3 py-2 text-left text-xs font-medium transition-[color,background-color,transform,box-shadow] duration-180 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary motion-reduce:transition-none ${
                section === id
                  ? 'bg-primary-soft text-primary shadow-sm'
                  : 'text-muted-foreground hover:-translate-y-px hover:bg-surface-muted hover:text-foreground'
              }`}
            >
              {icon}
              {label}
            </button>
          ))}
        </nav>
        <div className="min-w-0 space-y-4">
          {notice && <p role="status" className="flex items-center gap-2 rounded-lg border border-success/30 bg-success-soft px-3 py-2 text-sm text-success"><CheckCircle2 size={15} aria-hidden="true" />{notice}</p>}
          {section === 'settings' && (
            <>
              <Panel title="Runtime settings">
                <div className="grid gap-3 sm:grid-cols-3">
                  <Field label="Retrieval top-k">
                    <input className={inputClass} type="number" min={1} value={settingsDraft.top_k} onChange={(e) => setSettingsDraft({ ...settingsDraft, top_k: Number(e.target.value) })} />
                  </Field>
                  <Field label="Sufficiency threshold">
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
                  <Field label="Hop limit"><input className={inputClass} type="number" min={1} max={4} value={settingsDraft.hop_limit} onChange={(e) => setSettingsDraft({ ...settingsDraft, hop_limit: Number(e.target.value) })} /></Field>
                  <Field label="Retry limit"><input className={inputClass} type="number" min={0} value={settingsDraft.retry_limit} onChange={(e) => setSettingsDraft({ ...settingsDraft, retry_limit: Number(e.target.value) })} /></Field>
                  <Field label="Deep credit cap"><input className={inputClass} type="number" min={1} value={settingsDraft.deep_cap} onChange={(e) => setSettingsDraft({ ...settingsDraft, deep_cap: Number(e.target.value) })} /></Field>
                  <Field label="Abstention threshold"><input className={inputClass} type="number" min={0} max={1} step="0.01" value={settingsDraft.abstain_threshold} onChange={(e) => setSettingsDraft({ ...settingsDraft, abstain_threshold: Number(e.target.value) })} /></Field>
                  <Field label="Guardrails"><select className={inputClass} value={settingsDraft.guardrails ? 'on' : 'off'} onChange={(e) => setSettingsDraft({ ...settingsDraft, guardrails: e.target.value === 'on' })}><option value="on">Enabled</option><option value="off">Disabled</option></select></Field>
                  <Field label="Injection action"><select className={inputClass} value={settingsDraft.injection_action} onChange={(e) => setSettingsDraft({ ...settingsDraft, injection_action: e.target.value })}><option value="block">Block</option><option value="warn">Warn</option><option value="off">Off</option></select></Field>
                  <Field label="Web provider"><select className={inputClass} value={settingsDraft.web_provider} onChange={(e) => setSettingsDraft({ ...settingsDraft, web_provider: e.target.value })}><option value="tavily">Tavily</option><option value="brave">Brave</option></select></Field>
                  <Field label="Source priority"><select className={inputClass} value={settingsDraft.source_priority} onChange={(e) => setSettingsDraft({ ...settingsDraft, source_priority: e.target.value })}><option value="documents_first">Documents first</option><option value="web_first">Web first</option></select></Field>
                  <Field label="Trace sample rate"><input className={inputClass} type="number" min={0} max={1} step="0.01" value={settingsDraft.trace_sample_rate} onChange={(e) => setSettingsDraft({ ...settingsDraft, trace_sample_rate: Number(e.target.value) })} /></Field>
                </div>
                <p className="mt-3 font-mono text-[0.65rem] text-muted-foreground">Active v{current?.version ?? '—'} · top-k {currentTopK} · threshold {currentThreshold} · {currentMode}</p>
                 <button type="button" className={`${buttonClass} mt-4`} onClick={() => settingsSave.mutate()} disabled={settingsSave.isPending}><Save size={13} aria-hidden="true" />Create version</button>

              </Panel>
              <Panel title="Versions / rollback">
                <div className="divide-y divide-border">
                  {(versions.data ?? []).map((version: SettingsOut) => (
                     <div key={version.version} className="flex items-center justify-between gap-3 border-b border-border/70 px-1 py-2.5 last:border-b-0">
                       <div className="flex items-baseline gap-2"><span className="font-mono text-sm text-foreground">v{version.version}</span><span className="text-xs text-muted-foreground">{version.active ? 'active' : 'inactive'}</span></div>
                        {!version.active && <button type="button" className={buttonClass} onClick={() => rollback.mutate(version.version)} disabled={rollback.isPending}><RefreshCw size={13} aria-hidden="true" />Activate</button>}

                     </div>
                  ))}
                </div>
              </Panel>
            </>
          )}
          {section === 'providers' && (
            <Panel title="Providers">
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
                       <div className="truncate font-mono text-sm text-foreground">{provider.name}</div>
                       <div className="mt-0.5 truncate text-xs text-muted-foreground">
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
            <Panel title="Model catalogue">
              <div className="grid gap-3 sm:grid-cols-3">
                <Field label="Provider"><select className={inputClass} value={modelForm.provider_id} onChange={(e) => setModelForm({ ...modelForm, provider_id: e.target.value })}><option value="">Select provider</option>{(providers.data ?? []).map((provider: ProviderOut) => <option key={provider.id} value={provider.id}>{provider.name}</option>)}</select></Field>
                <Field label="Model ID"><input className={inputClass} value={modelForm.model_id} onChange={(e) => setModelForm({ ...modelForm, model_id: e.target.value })} /></Field>
                <Field label="Context window"><input className={inputClass} type="number" value={modelForm.context_window ?? ''} onChange={(e) => setModelForm({ ...modelForm, context_window: Number(e.target.value) })} /></Field>
                <Field label="Input price"><input className={inputClass} type="number" step="0.000001" value={modelForm.price_in ?? ''} onChange={(e) => setModelForm({ ...modelForm, price_in: Number(e.target.value) })} /></Field>
                <Field label="Output price"><input className={inputClass} type="number" step="0.000001" value={modelForm.price_out ?? ''} onChange={(e) => setModelForm({ ...modelForm, price_out: Number(e.target.value) })} /></Field>
              </div>
               <button type="button" className={`${buttonClass} mt-4`} onClick={() => modelCreate.mutate(modelForm)} disabled={modelCreate.isPending || !modelForm.provider_id || !modelForm.model_id}><Plus size={13} aria-hidden="true" />Add model</button>

               <div className="mt-5 border-t border-border/70 pt-3">
                 <TableHeader left="Model / limits" right="Actions" />
                 {(models.data ?? []).filter((model: AdminModelOut) => !isDecisionModel(model)).map((model: AdminModelOut) => (
                   <TableRow key={model.id}>
                     <div className="min-w-0">
                       <div className="truncate font-mono text-sm text-foreground">{model.model_id}</div>
                       <div className="mt-0.5 text-xs text-muted-foreground">
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
             <Panel title="Model roles">
               <div className="border-t border-border/70 pt-3">
                 <TableHeader left="Role" right="Assigned model" />
                 {(roles.data ?? []).map((role: RoleOut) => (
                   <TableRow key={role.role}>
                     <span className="min-w-0 truncate font-mono text-sm text-foreground">{role.role}</span>
                     <select className={inputClass} value={role.model_id} onChange={(e) => roleSave.mutate({ role: role.role, model_id: e.target.value, fallback_model_id: role.fallback_model_id ?? undefined })}>
                       {(models.data ?? []).map((model: AdminModelOut) => <option key={model.id} value={model.model_id}>{model.model_id}</option>)}
                     </select>
                   </TableRow>
                 ))}
               </div>
             </Panel>
          )}
          {section === 'plans' && (
            <Panel title="Plans and quota overrides">
              <div className="grid gap-3 sm:grid-cols-3"><Field label="Name"><input className={inputClass} value={planForm.name} onChange={(e) => setPlanForm({ ...planForm, name: e.target.value })} /></Field><Field label="5h credits"><input className={inputClass} type="number" value={planForm.credits_5h} onChange={(e) => setPlanForm({ ...planForm, credits_5h: Number(e.target.value) })} /></Field><Field label="Monthly credits"><input className={inputClass} type="number" value={planForm.credits_month} onChange={(e) => setPlanForm({ ...planForm, credits_month: Number(e.target.value) })} /></Field></div>
               <button type="button" className={`${buttonClass} mt-4`} onClick={() => planCreate.mutate()} disabled={planCreate.isPending}><Plus size={13} aria-hidden="true" />Add plan</button>

               <div className="mt-5 border-t border-border/70 pt-3">
                 <TableHeader left="Plan / 5h credits" right="Monthly / action" />
                 {(plans.data ?? []).map((plan: PlanOut) => <PlanRow key={plan.id} plan={plan} onSave={(body) => planUpdate.mutate({ id: plan.id, body })} />)}
               </div>
            </Panel>
          )}
          {section === 'users' && (
             <Panel title="Users">
               <div className="border-t border-border/70 pt-3">
                 <TableHeader left="User / role" right="Overrides" />
                 {(users.data ?? []).map((user: UserOut) => <UserRow key={user.id} user={user} onUpdate={(body) => userUpdate.mutate({ id: user.id, body })} />)}
               </div>
             </Panel>
          )}
          {section === 'audit' && (
             <Panel title="Audit log">
               <div className="border-t border-border/70 pt-3">
                 <TableHeader left="Action / target" right="Time" />
                 {(audit.data ?? []).map((row: AuditOut) => (
                   <TableRow key={row.id}>
                     <div className="min-w-0">
                       <div className="truncate font-mono text-sm text-foreground">{row.action}</div>
                       <div className="mt-0.5 truncate text-xs text-muted-foreground">{row.target}</div>
                     </div>
                     <span className="shrink-0 text-xs text-muted-foreground">{new Date(row.created_at).toLocaleString()}</span>
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
        <div className="truncate text-sm text-foreground">{user.email}</div>
        <div className="mt-0.5 text-xs text-muted-foreground">{user.role} · {user.status}</div>
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
        <div className="truncate font-mono text-sm text-foreground">{plan.name}</div>
        <div className="mt-0.5 text-xs text-muted-foreground">5h {plan.credits_5h}</div>
      </div>
      <div className="flex items-center gap-2">
        <input aria-label={`${plan.name} monthly credits`} className={inputClass} type="number" value={month} onChange={(e) => setMonth(Number(e.target.value))} />
         <button type="button" className={buttonClass} onClick={() => onSave({ credits_month: month })}><Save size={13} aria-hidden="true" />Save</button>

      </div>
    </TableRow>
  )
}
