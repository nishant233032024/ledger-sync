"use client";

import { useDeferredValue, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { flexRender, getCoreRowModel, useReactTable, type ColumnDef } from "@tanstack/react-table";
import { useVirtualizer } from "@tanstack/react-virtual";
import { CheckCircle2, CircleDollarSign, FileSpreadsheet, LogOut, RefreshCw, Search, TriangleAlert, UploadCloud } from "lucide-react";

import { getBatches, getDiscrepancies, getMe, getRuns, getSummary, getTransactions, login, PUBLIC_DEMO, resolveDiscrepancy, startReconciliation, uploadBatch } from "@/lib/api";
import type { Batch, Discrepancy, PagedResponse, ReconciliationRun, SourceType, Transaction } from "@/lib/types";
import { Badge, Button, Card, Input } from "@/components/ui";

const selectClass = "mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-normal";

function statusTone(status: string): "slate" | "green" | "amber" | "rose" {
  if (["MATCHED", "COMPLETED", "RESOLVED"].includes(status)) return "green";
  if (["PROCESSING", "PENDING", "IN_REVIEW"].includes(status)) return "amber";
  if (["FAILED", "DISCREPANCY", "OPEN"].includes(status)) return "rose";
  return "slate";
}

function MetricCard({ title, value, icon }: { title: string; value: string | number; icon: ReactNode }) {
  return <Card className="flex items-start justify-between gap-2">
    <div><p className="text-sm font-medium text-slate-500">{title}</p><p className="mt-2 text-3xl font-bold text-ink">{value}</p></div>
    <div className="rounded-xl bg-teal-50 p-3 text-brand">{icon}</div>
  </Card>;
}

export function LoginPanel({ onLogin }: { onLogin: () => void }) {
  const [username, setUsername] = useState(PUBLIC_DEMO ? "demo@example.com" : "admin@example.com");
  const [password, setPassword] = useState(PUBLIC_DEMO ? "Demo12345!" : "Admin12345!");
  const mutation = useMutation({ mutationFn: () => login(username, password), onSuccess: onLogin });
  return <main className="flex min-h-screen items-center justify-center bg-slate-950 px-4">
    <Card className="w-full max-w-md border-slate-700 bg-white p-8">
      <div className="mb-8 flex items-center gap-3">
        <div className="rounded-xl bg-brand p-3 text-white"><CircleDollarSign /></div>
        <div><h1 className="text-2xl font-bold">LedgerSync</h1><p className="text-sm text-slate-500">Finance operations workspace</p></div>
      </div>
      <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); mutation.mutate(); }}>
        <label className="block text-sm font-semibold text-slate-700">Username<Input required value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" /></label>
        <label className="block text-sm font-semibold text-slate-700">Password<Input required type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" /></label>
        {mutation.isError && <p role="alert" className="rounded-lg bg-rose-50 p-3 text-sm text-rose-700">{mutation.error.message}</p>}
        <Button className="w-full" disabled={mutation.isPending}>{mutation.isPending ? "Signing in..." : "Sign in"}</Button>
      </form>
      <p className="mt-6 text-xs text-slate-500">Demo: {PUBLIC_DEMO ? "demo@example.com / Demo12345!" : "admin@example.com / Admin12345!"}</p>
      {PUBLIC_DEMO && <p className="mt-3 text-xs leading-relaxed text-slate-500">Read-only interview demo with verified BenchRec results. The free backend may take about a minute to wake up on the first sign-in.</p>}
    </Card>
  </main>;
}

function UploadCard({ onUploaded }: { onUploaded: (batchId: string, sourceType: SourceType) => void }) {
  const fileInput = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [sourceType, setSourceType] = useState<SourceType>("ERP");
  const [sourceAccount, setSourceAccount] = useState("primary");
  const [progress, setProgress] = useState(0);
  const mutation = useMutation({
    mutationFn: () => uploadBatch(file!, sourceType, sourceAccount, setProgress),
    onSuccess: (result) => {
      onUploaded(result.data.id, sourceType);
      setFile(null);
      setProgress(0);
      if (fileInput.current) fileInput.current.value = "";
    },
  });
  return <Card>
    <div className="mb-5 flex items-center gap-3"><UploadCloud className="text-brand" /><div><h2 className="font-bold">Upload source batch</h2><p className="text-sm text-slate-500">CSV, XLSX, or XLS. Required columns: reference, amount, currency, timestamp.</p></div></div>
    <form className="grid gap-4 md:grid-cols-2" onSubmit={(event) => { event.preventDefault(); if (file) mutation.mutate(); }}>
      <label className="flex cursor-pointer items-center gap-3 rounded-lg border-2 border-dashed border-slate-300 px-4 py-3 text-sm hover:border-brand">
        <FileSpreadsheet className="text-brand" /><span className="truncate">{file?.name ?? "Choose a file"}</span>
        <input ref={fileInput} aria-label="Source file" type="file" accept=".csv,.xlsx,.xls" className="sr-only" disabled={mutation.isPending} onChange={(event) => { mutation.reset(); setFile(event.target.files?.[0] ?? null); }} />
      </label>
      <label className="text-sm font-semibold text-slate-700">Source<select value={sourceType} disabled={mutation.isPending} onChange={(event) => setSourceType(event.target.value as SourceType)} className={selectClass}><option value="ERP">ERP ledger</option><option value="BANK">Bank statement</option><option value="GATEWAY">Payment gateway</option></select></label>
      <label className="text-sm font-semibold text-slate-700">Source account<Input required pattern="[A-Za-z0-9._-]{1,100}" value={sourceAccount} disabled={mutation.isPending} onChange={(event) => setSourceAccount(event.target.value)} /><span className="text-xs font-normal text-slate-500">Use a separate account name for each independent sample exercise.</span></label>
      <div className="self-center"><Button disabled={!file || mutation.isPending}>{mutation.isPending ? `Uploading ${progress}%` : "Upload batch"}</Button></div>
    </form>
    {mutation.isError && <p role="alert" className="mt-3 text-sm text-rose-600">{mutation.error.message}</p>}
    {mutation.isPending && <div className="mt-4 h-2 overflow-hidden rounded-full bg-slate-100"><div className="h-full bg-brand transition-all" style={{ width: `${progress}%` }} /></div>}
  </Card>;
}

function BatchCard({ batch, isSelected, onSelect }: { batch: Batch; isSelected: boolean; onSelect: () => void }) {
  return <button onClick={onSelect} className={`w-full rounded-xl border p-4 text-left transition ${isSelected ? "border-brand bg-teal-50" : "border-slate-200 bg-white hover:border-teal-300"}`}>
    <div className="flex items-start justify-between gap-3"><div className="min-w-0"><p className="truncate font-semibold">{batch.original_filename}</p><p className="mt-1 text-xs text-slate-500">{batch.source_type} · {batch.imported_records} imported · {batch.duplicate_records} repeated</p><p className="mt-1 truncate text-xs text-slate-400">{batch.source_account}</p></div><Badge tone={statusTone(batch.status)}>{batch.status}</Badge></div>
    <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-100"><div className="h-full bg-brand" style={{ width: `${batch.progress_percentage}%` }} /></div>
    {batch.error_message && <p className="mt-2 text-xs text-rose-700">{batch.error_message}</p>}
  </button>;
}

function TransactionTable({ rows }: { rows: Transaction[] }) {
  const columns = useMemo<ColumnDef<Transaction>[]>(() => [
    { accessorKey: "reference", header: "Reference" },
    { accessorKey: "counterparty", header: "Counterparty" },
    { accessorKey: "amount", header: "Amount", cell: ({ row }) => `${row.original.currency} ${row.original.amount}` },
    { accessorKey: "timestamp", header: "Timestamp", cell: ({ row }) => new Date(row.original.timestamp).toLocaleString() },
    { accessorKey: "status", header: "Status", cell: ({ row }) => <Badge tone={statusTone(row.original.status)}>{row.original.status}</Badge> },
  ], []);
  const table = useReactTable({ data: rows, columns, getCoreRowModel: getCoreRowModel() });
  const parentRef = useRef<HTMLDivElement>(null);
  const virtualizer = useVirtualizer({ count: table.getRowModel().rows.length, getScrollElement: () => parentRef.current, estimateSize: () => 56, overscan: 8 });
  return <div ref={parentRef} className="h-[460px] overflow-auto rounded-xl border border-slate-200">
    <div className="min-w-[760px]">
      <div className="sticky top-0 z-10 grid grid-cols-5 gap-4 border-b border-slate-200 bg-slate-50 px-4 py-3 text-xs font-bold uppercase tracking-wide text-slate-500">{table.getHeaderGroups()[0].headers.map((header) => <div key={header.id}>{flexRender(header.column.columnDef.header, header.getContext())}</div>)}</div>
      <div className="relative" style={{ height: `${virtualizer.getTotalSize()}px` }}>{virtualizer.getVirtualItems().map((virtualRow) => {
        const row = table.getRowModel().rows[virtualRow.index];
        return <div key={row.id} className="absolute left-0 grid w-full grid-cols-5 gap-4 border-b border-slate-100 px-4 py-3 text-sm" style={{ height: `${virtualRow.size}px`, transform: `translateY(${virtualRow.start}px)` }}>
          {row.getVisibleCells().map((cell) => <div key={cell.id} className="truncate text-slate-700">{flexRender(cell.column.columnDef.cell, cell.getContext())}</div>)}
        </div>;
      })}</div>
      {rows.length === 0 && <p className="p-6 text-sm text-slate-500">No transactions match these filters.</p>}
    </div>
  </div>;
}

function Pagination({ meta, page, onPage }: { meta?: PagedResponse<unknown>["meta"]; page: number; onPage: (page: number) => void }) {
  return <div className="mt-4 flex flex-wrap items-center justify-between gap-3 text-sm text-slate-500">
    <p>{meta ? `${meta.total.toLocaleString()} records · page ${meta.page} of ${Math.max(1, Math.ceil(meta.total / meta.page_size))}` : "Loading records..."}</p>
    <div className="flex gap-2"><Button variant="secondary" disabled={!meta?.has_previous} onClick={() => onPage(page - 1)}>Previous</Button><Button variant="secondary" disabled={!meta?.has_next} onClick={() => onPage(page + 1)}>Next</Button></div>
  </div>;
}

function DiscrepancyReview({ rows, canWrite, onResolved }: { rows: Discrepancy[]; canWrite: boolean; onResolved: () => void }) {
  const client = useQueryClient();
  const [note, setNote] = useState<Record<string, string>>({});
  const mutation = useMutation({
    mutationFn: ({ id, text }: { id: string; text: string }) => resolveDiscrepancy(id, "ACCEPTED_VARIANCE", text),
    onSuccess: () => {
      onResolved();
      void client.invalidateQueries({ queryKey: ["discrepancies"] });
      void client.invalidateQueries({ queryKey: ["summary"] });
    },
  });
  return <div className="space-y-3">
    {mutation.isError && <p role="alert" className="text-sm text-rose-700">{mutation.error.message}</p>}
    {rows.length === 0 && <p className="rounded-xl bg-emerald-50 p-6 text-center text-sm text-emerald-700">No open discrepancies in this selection.</p>}
    {rows.map((item) => <div key={item.id} className="rounded-xl border border-rose-100 bg-rose-50/40 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3"><div><p className="font-bold text-slate-800">{item.discrepancy_type.replaceAll("_", " ")}</p><p className="mt-1 text-sm text-slate-600">{item.primary_reference} · {item.primary_amount}{item.secondary_reference ? ` vs ${item.secondary_reference} · ${item.secondary_amount}` : ""}</p><p className="mt-1 text-xs text-rose-700">{item.details.reason}</p></div><Badge tone={statusTone(item.status)}>{item.status}</Badge></div>
      {canWrite && item.status === "OPEN" && <div className="mt-4 flex flex-col gap-2 sm:flex-row"><Input aria-label={`Audit note for ${item.primary_reference}`} placeholder="Required audit note (10+ characters)" value={note[item.id] ?? ""} onChange={(event) => setNote((current) => ({ ...current, [item.id]: event.target.value }))} /><Button disabled={(note[item.id] ?? "").trim().length < 10 || mutation.isPending} onClick={() => mutation.mutate({ id: item.id, text: note[item.id] })}>Resolve</Button></div>}
    </div>)}
  </div>;
}

function scenarioLabel(run: ReconciliationRun, batches: Batch[]): string {
  const filename = batches.find((batch) => batch.id === run.ledger_batch_id)?.original_filename;
  return filename?.replace(/_ledger\.csv$/, "").replaceAll("_", " ") ?? `Run ${run.id.slice(0, 8)}`;
}

export function LedgerDashboard({ onLogout }: { onLogout: () => void }) {
  const client = useQueryClient();
  const [activeView, setActiveView] = useState<"overview" | "transactions" | "discrepancies">("overview");
  const [selectedLedgerId, setSelectedLedgerId] = useState("");
  const [selectedExternalId, setSelectedExternalId] = useState("");
  const [selectedRunId, setSelectedRunId] = useState(PUBLIC_DEMO ? "" : "all");
  const [transactionPage, setTransactionPage] = useState(1);
  const [discrepancyPage, setDiscrepancyPage] = useState(1);
  const [search, setSearch] = useState("");
  const deferredSearch = useDeferredValue(search);
  const [transactionStatus, setTransactionStatus] = useState("");

  const meQuery = useQuery({ queryKey: ["me"], queryFn: getMe });
  const batchesQuery = useQuery({
    queryKey: ["batches"], queryFn: getBatches,
    refetchInterval: (query) => query.state.data?.data.some((batch) => ["PENDING", "PROCESSING"].includes(batch.status)) ? 1500 : false,
  });
  const runsQuery = useQuery({
    queryKey: ["runs"], queryFn: getRuns,
    refetchInterval: (query) => query.state.data?.data.some((run) => ["PENDING", "PROCESSING"].includes(run.status)) ? 1500 : false,
  });
  const batches = batchesQuery.data?.data ?? [];
  const runs = runsQuery.data?.data ?? [];
  const runId = selectedRunId && selectedRunId !== "all" ? selectedRunId : undefined;
  const selectedRun = runs.find((run) => run.id === runId);
  const canWrite = Boolean(meQuery.data && !meQuery.data.data.read_only);
  const summaryQuery = useQuery({ queryKey: ["summary", runId], queryFn: () => getSummary(runId), enabled: selectedRunId !== "" });
  const transactionsQuery = useQuery({
    queryKey: ["transactions", runId, deferredSearch, transactionStatus, transactionPage],
    queryFn: () => getTransactions({ page: transactionPage, page_size: 100, search: deferredSearch, status: transactionStatus, run_id: runId }),
    enabled: activeView === "transactions" && selectedRunId !== "",
  });
  const discrepanciesQuery = useQuery({
    queryKey: ["discrepancies", runId, discrepancyPage],
    queryFn: () => getDiscrepancies({ status: "OPEN", page: discrepancyPage, run_id: runId }),
    enabled: activeView === "discrepancies" && selectedRunId !== "",
  });
  const runMutation = useMutation({
    mutationFn: ({ ledger, external }: { ledger: string; external: string }) => startReconciliation(ledger, external),
    onSuccess: (result) => { setSelectedRunId(result.data.id); void client.invalidateQueries({ queryKey: ["runs"] }); },
  });

  // The controlled exercise is the clearest first view for an interviewer.
  useEffect(() => {
    if (selectedRunId === "" && runsQuery.isSuccess && batchesQuery.isSuccess) {
      const controlled = runsQuery.data.data.find((run) => batchesQuery.data.data.some(
        (batch) => batch.id === run.ledger_batch_id && batch.original_filename === "controlled_faults_2023_ledger.csv",
      ));
      setSelectedRunId(controlled?.id ?? "all");
    }
  }, [selectedRunId, runsQuery.isSuccess, runsQuery.data, batchesQuery.isSuccess, batchesQuery.data]);

  const jobStates = [...batches, ...runs].map((job) => `${job.id}:${job.status}`).join("|");
  useEffect(() => {
    // Invalidate after worker transitions, rather than immediately after only
    // enqueueing a job. This keeps totals and exceptions in sync with SQL.
    void client.invalidateQueries({ queryKey: ["summary"] });
    void client.invalidateQueries({ queryKey: ["transactions"] });
    void client.invalidateQueries({ queryKey: ["discrepancies"] });
  }, [client, jobStates]);

  const ledgerBatches = batches.filter((batch) => batch.source_type === "ERP" && batch.status === "COMPLETED");
  const externalBatches = batches.filter((batch) => batch.source_type !== "ERP" && batch.status === "COMPLETED");
  const ledgerId = selectedLedgerId || ledgerBatches[0]?.id || "";
  const externalId = selectedExternalId || externalBatches[0]?.id || "";
  const existingRun = runs.find((run) => run.ledger_batch_id === ledgerId && run.external_batch_id === externalId);
  const summary = summaryQuery.data?.data;
  const variances = Object.entries(summary?.variance_by_currency ?? {});
  const varianceLabel = !summary ? "—" : variances.length === 0 ? "0" : variances.length === 1
    ? `${variances[0][0]} ${Number(variances[0][1]).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 })}`
    : "Multiple currencies";
  const error = [meQuery.error, batchesQuery.error, runsQuery.error, summaryQuery.error,
    activeView === "transactions" ? transactionsQuery.error : null,
    activeView === "discrepancies" ? discrepanciesQuery.error : null].find(Boolean);
  const chooseRun = (value: string) => { setSelectedRunId(value); setTransactionPage(1); setDiscrepancyPage(1); };
  const onUploaded = (id: string, sourceType: SourceType) => {
    void client.invalidateQueries({ queryKey: ["batches"] });
    // The new batch becomes selectable after its worker finishes.
    if (sourceType === "ERP") setSelectedLedgerId(id);
    else setSelectedExternalId(id);
  };

  return <div className="min-h-screen bg-surface">
    <header className="border-b border-slate-200 bg-white"><div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-4 py-4 sm:px-6">
      <div className="flex items-center gap-3"><div className="rounded-xl bg-brand p-2 text-white"><CircleDollarSign size={22} /></div><div><h1 className="font-bold text-ink">LedgerSync</h1><p className="text-xs text-slate-500">{meQuery.data?.data.organization ?? "Financial reconciliation control room"}</p></div></div>
      <Button variant="secondary" onClick={onLogout}><LogOut size={16} className="mr-2 inline" />Sign out</Button>
    </div></header>
    <main className="mx-auto max-w-7xl space-y-6 px-4 py-6 sm:px-6">
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
        <div><p className="text-sm font-semibold uppercase tracking-wider text-brand">Operations dashboard</p><h2 className="mt-1 text-3xl font-bold text-ink">Reconcile with confidence</h2><p className="mt-1 text-slate-500">Inspect matching decisions, source records, and documented exceptions.</p></div>
        <nav aria-label="Dashboard sections" className="flex flex-wrap gap-2">{(["overview", "transactions", "discrepancies"] as const).map((view) => <Button key={view} variant={activeView === view ? "primary" : "secondary"} onClick={() => setActiveView(view)}>{view[0].toUpperCase() + view.slice(1)}</Button>)}</nav>
      </div>
      {meQuery.data?.data.public_demo && <div className="rounded-xl border border-teal-200 bg-teal-50 p-4 text-sm leading-relaxed text-teal-900"><strong>Read-only public interview demo.</strong> These results were computed by the reconciliation engine from BenchRec files and verified against separate evidence. The controlled exercise injects known defects; historical exceptions are rule-review flags, not proof of bank errors. <a className="font-semibold underline" href="https://www.kaggle.com/datasets/benchmarkteam/benchrec-real-world-cash-reconciliation-dataset" target="_blank" rel="noreferrer">BenchRec / Operartis · CC BY 4.0</a></div>}
      {error && <p role="alert" className="rounded-xl bg-rose-50 p-4 text-sm text-rose-700">{error.message} <Button variant="secondary" className="ml-2" onClick={() => void client.invalidateQueries()}>Retry</Button></p>}
      <Card>
        <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
          <label className="min-w-0 flex-1 text-sm font-semibold text-slate-700">Reconciliation scenario<select aria-label="Reconciliation scenario" className={selectClass} value={selectedRunId} onChange={(event) => chooseRun(event.target.value)}>
            {selectedRunId === "" && <option value="">Loading scenarios...</option>}
            <option value="all">All uploaded data</option>
            {runs.map((run) => <option key={run.id} value={run.id}>{scenarioLabel(run, batches)} · {run.matched_count} matches · {run.discrepancy_count} flags · {run.status}</option>)}
          </select></label>
          <Button variant="secondary" onClick={() => void client.invalidateQueries()}><RefreshCw size={16} className="mr-2 inline" />Refresh</Button>
        </div>
        {selectedRun && <p className="mt-3 text-sm text-slate-500">Run {selectedRun.id.slice(0, 8)} · {selectedRun.status}{selectedRun.error_message ? ` · ${selectedRun.error_message}` : ""}. {scenarioLabel(selectedRun, batches).startsWith("controlled faults") ? "Known injected defects: expected 93 matches and 11 flags." : scenarioLabel(selectedRun, batches).startsWith("control baseline") ? "Compatible curated pairs: expected 100 matches and no flags." : "Historical sample: the exact-reference rule deliberately leaves uncertain pairs for review."}</p>}
      </Card>
      {activeView === "overview" && <>
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <MetricCard title="Transactions uploaded" value={summary?.total_uploaded ?? "—"} icon={<FileSpreadsheet size={20} />} />
          <MetricCard title="Match rate (ERP rows)" value={summary ? `${summary.match_rate}%` : "—"} icon={<CheckCircle2 size={20} />} />
          <MetricCard title="Open discrepancies" value={summary?.pending_discrepancies ?? "—"} icon={<TriangleAlert size={20} />} />
          <MetricCard title="Open measured variance" value={varianceLabel} icon={<CircleDollarSign size={20} />} />
        </div>
        {variances.length > 1 && <p className="text-sm text-slate-500">Variance by currency: {variances.map(([currency, value]) => `${currency} ${value}`).join(" · ")}</p>}
        {canWrite && <UploadCard onUploaded={onUploaded} />}
        <div className="grid gap-6 lg:grid-cols-2">
          <Card><h3 className="mb-4 font-bold">Source batches</h3><div className="max-h-[480px] space-y-3 overflow-auto">
            {batches.length === 0 && <p className="text-sm text-slate-500">{batchesQuery.isPending ? "Loading batches..." : "Upload an ERP ledger and an external statement to get started."}</p>}
            {batches.map((batch) => <BatchCard key={batch.id} batch={batch} isSelected={batch.id === ledgerId || batch.id === externalId} onSelect={() => { if (batch.status !== "COMPLETED") return; if (batch.source_type === "ERP") setSelectedLedgerId(batch.id); else setSelectedExternalId(batch.id); }} />)}
          </div></Card>
          <Card><h3 className="font-bold">Reconciliation workflow</h3><p className="mt-2 text-sm text-slate-500">Compare two completed batches using a snapshotted matching rule.</p>
            <div className="mt-5 space-y-4">
              <label className="block text-sm font-semibold text-slate-700">ERP ledger<select aria-label="ERP ledger batch" className={selectClass} value={ledgerId} onChange={(event) => setSelectedLedgerId(event.target.value)}><option value="">Choose a completed ERP batch</option>{ledgerBatches.map((batch) => <option key={batch.id} value={batch.id}>{batch.original_filename} · {batch.source_account}</option>)}</select></label>
              <label className="block text-sm font-semibold text-slate-700">External statement<select aria-label="External statement batch" className={selectClass} value={externalId} onChange={(event) => setSelectedExternalId(event.target.value)}><option value="">Choose a completed BANK / GATEWAY batch</option>{externalBatches.map((batch) => <option key={batch.id} value={batch.id}>{batch.original_filename} · {batch.source_account}</option>)}</select></label>
              {canWrite && <Button disabled={!ledgerId || !externalId || Boolean(existingRun) || runMutation.isPending} onClick={() => runMutation.mutate({ ledger: ledgerId, external: externalId })}>{runMutation.isPending ? "Starting..." : "Start reconciliation"}</Button>}
              {existingRun && <div className="rounded-lg bg-slate-50 p-3 text-sm"><Badge tone={statusTone(existingRun.status)}>{existingRun.status}</Badge><p className="mt-2">{existingRun.matched_count} matched pairs · {existingRun.discrepancy_count} flags</p><Button variant="secondary" className="mt-3" onClick={() => chooseRun(existingRun.id)}>View this run</Button></div>}
              {!canWrite && <p className="text-sm text-slate-500">Auditor access: inspect the precomputed runs with the scenario selector. The Docker demonstration supports uploads, background jobs, and audited resolutions.</p>}
              {runMutation.isError && <p role="alert" className="text-sm text-rose-700">{runMutation.error.message}</p>}
            </div>
          </Card>
        </div>
      </>}
      {activeView === "transactions" && <Card>
        <div className="mb-5 flex flex-col justify-between gap-3 sm:flex-row"><h3 className="font-bold">Normalized transactions</h3><div className="flex flex-col gap-2 sm:flex-row"><div className="relative"><Search size={16} className="absolute left-3 top-3 text-slate-400" /><Input aria-label="Search transactions" className="pl-9" placeholder="Search reference or counterparty" value={search} onChange={(event) => { setSearch(event.target.value); setTransactionPage(1); }} /></div><select aria-label="Transaction status" className={selectClass} value={transactionStatus} onChange={(event) => { setTransactionStatus(event.target.value); setTransactionPage(1); }}><option value="">All statuses</option>{["UNRECONCILED", "MATCHED", "DISCREPANCY", "IGNORED"].map((status) => <option key={status}>{status}</option>)}</select></div></div>
        {transactionsQuery.isPending ? <p className="p-6 text-sm text-slate-500">Loading transactions...</p> : <TransactionTable rows={transactionsQuery.data?.data ?? []} />}
        <Pagination meta={transactionsQuery.data?.meta} page={transactionPage} onPage={setTransactionPage} />
      </Card>}
      {activeView === "discrepancies" && <Card>
        <h3 className="mb-4 font-bold">Open discrepancy review</h3>
        {discrepanciesQuery.isPending ? <p className="p-6 text-sm text-slate-500">Loading discrepancies...</p> : <DiscrepancyReview rows={discrepanciesQuery.data?.data ?? []} canWrite={canWrite} onResolved={() => setDiscrepancyPage(1)} />}
        <Pagination meta={discrepanciesQuery.data?.meta} page={discrepancyPage} onPage={setDiscrepancyPage} />
      </Card>}
    </main>
  </div>;
}
