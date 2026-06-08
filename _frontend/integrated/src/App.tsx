import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  Activity,
  ArrowUpRight,
  CheckCircle2,
  ClipboardCheck,
  Clock3,
  Database,
  FileInput,
  Gauge,
  Home,
  Loader2,
  LockKeyhole,
  PlayCircle,
  RefreshCw,
  Server,
  ShieldCheck,
  Square,
  Upload,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

type Service = {
  key: string;
  name: string;
  path: string;
  port: number;
  ready: boolean;
};

type ProcessInfo = {
  name: string;
  pid: number;
  returncode: number | null;
};

type StatusPayload = {
  processes: ProcessInfo[];
  services: Service[];
  browser_lock: boolean;
  logs: string[];
  version: string;
};

type PreviewItem = {
  key: string;
  name: string;
  output: string;
  selected: boolean;
  incoming_count: number;
  existing_count: number;
  added_count: number;
  changed_count: number;
  removed_count: number;
  incoming_names: string[];
  changed_names: string[];
  removed_names: string[];
  missing_required: string[];
};

type PreviewPayload = {
  targets: Record<string, PreviewItem>;
  selected: string[];
};

const serviceMeta: Record<string, { icon: typeof Activity; tone: string; description: string }> = {
  xhs: { icon: ClipboardCheck, tone: "text-rose-600", description: "浏览器脚本队列、手动触发、Docker 下载" },
  x: { icon: Activity, tone: "text-sky-600", description: "喜欢内容、媒体库、手动下载" },
  pixiv: { icon: ShieldCheck, tone: "text-indigo-600", description: "OAuth、收藏下载、429 保护" },
  douyin: { icon: PlayCircle, tone: "text-orange-600", description: "f2 点赞/收藏、版本检查、任务日志" },
};

const targets = [
  { key: "xhs", label: "小红书", output: "/config/xhs/xhs_cookie.txt" },
  { key: "x", label: "X", output: "/config/x/x_cookies.txt" },
  { key: "douyin", label: "抖音", output: "/config/douyin/douyin_cookie.txt + f2 YAML" },
];

const serviceActions: Record<string, { label: string; path: string; variant?: "default" | "secondary" | "outline" | "destructive" }[]> = {
  xhs: [
    { label: "立即运行", path: "/api/run-now" },
  ],
  x: [
    { label: "立即运行", path: "/run" },
    { label: "重载配置", path: "/reload", variant: "outline" },
  ],
  pixiv: [
    { label: "立即运行", path: "/run" },
    { label: "生成登录链接", path: "/oauth-start", variant: "secondary" },
    { label: "重载配置", path: "/reload", variant: "outline" },
  ],
  douyin: [
    { label: "全部运行", path: "/run" },
    { label: "停止", path: "/stop", variant: "destructive" },
    { label: "检查 f2", path: "/check-version", variant: "outline" },
  ],
};

const initialStatus: StatusPayload = {
  processes: [],
  services: [],
  browser_lock: false,
  logs: [],
  version: "",
};

function compactNames(names?: string[]) {
  if (!names?.length) return "无";
  const visible = names.slice(0, 12).join(", ");
  return names.length > 12 ? `${visible} ...` : visible;
}

async function postFormJson<T>(url: string, form: FormData): Promise<T> {
  const response = await fetch(url, { method: "POST", body: form });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return (await response.json()) as T;
}

function useStatus() {
  const [status, setStatus] = useState<StatusPayload>(initialStatus);
  const [loading, setLoading] = useState(true);

  async function refresh() {
    try {
      const response = await fetch("/api/status", { cache: "no-store" });
      setStatus((await response.json()) as StatusPayload);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    const timer = window.setInterval(refresh, 3000);
    return () => window.clearInterval(timer);
  }, []);

  return { status, loading, refresh };
}

function useServiceStatus(service?: Service) {
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function refresh() {
    if (!service) return;
    setLoading(true);
    try {
      const response = await fetch(`${service.path}api/status`, { cache: "no-store" });
      if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
      setData((await response.json()) as Record<string, unknown>);
      setError("");
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }

  async function runAction(path: string) {
    if (!service) return;
    setLoading(true);
    try {
      const response = await fetch(`${service.path.replace(/\/$/, "")}${path}`, {
        method: "POST",
        redirect: "follow",
      });
      if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
      setError("");
      await refresh();
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    if (!service) return;
    const timer = window.setInterval(refresh, 5000);
    return () => window.clearInterval(timer);
  }, [service?.key]);

  return { data, loading, error, refresh, runAction };
}

function App() {
  const { status, loading, refresh } = useStatus();
  const [active, setActive] = useState("overview");
  const [selectedTargets, setSelectedTargets] = useState(() => new Set(targets.map((item) => item.key)));
  const [preview, setPreview] = useState<PreviewPayload | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState<"preview" | "import" | "">("");

  const readyCount = status.services.filter((item) => item.ready).length;
  const activeService = status.services.find((item) => item.key === active);

  const formData = (form: HTMLFormElement) => {
    const data = new FormData(form);
    data.delete("targets");
    selectedTargets.forEach((key) => data.append("targets", key));
    return data;
  };

  async function previewCookies(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy("preview");
    setMessage("");
    try {
      setPreview(await postFormJson<PreviewPayload>("/api/cookie-preview", formData(event.currentTarget)));
    } catch (error) {
      setMessage(`预览失败：${error}`);
    } finally {
      setBusy("");
    }
  }

  async function importCookies(form: HTMLFormElement) {
    setBusy("import");
    setMessage("");
    try {
      const result = await postFormJson<{ ok: boolean; message: string }>("/api/cookie-import", formData(form));
      setMessage(result.message);
      await refresh();
    } catch (error) {
      setMessage(`导入失败：${error}`);
    } finally {
      setBusy("");
    }
  }

  const logs = useMemo(() => status.logs.slice(-80).join("\n"), [status.logs]);

  return (
    <div className="min-h-screen bg-background text-foreground">
      <div className="grid min-h-screen lg:grid-cols-[280px_minmax(0,1fr)]">
        <aside className="border-r bg-slate-950 text-slate-100">
          <div className="sticky top-0 flex h-screen flex-col gap-5 p-4">
            <div className="rounded-lg border border-white/10 bg-white/[0.03] p-4">
              <div className="flex items-center gap-3">
                <div className="grid h-10 w-10 place-items-center rounded-md bg-teal-400 text-slate-950">
                  <Database className="h-5 w-5" />
                </div>
                <div>
                  <div className="text-lg font-semibold">NAS Auto</div>
                  <div className="text-xs text-slate-400">{status.version || "v1.5.1-dev"}</div>
                </div>
              </div>
            </div>

            <nav className="grid gap-2">
              <button
                type="button"
                onClick={() => setActive("overview")}
                className={cn(
                  "flex items-center justify-between rounded-md px-3 py-2 text-left text-sm transition",
                  active === "overview" ? "bg-white text-slate-950" : "text-slate-300 hover:bg-white/10 hover:text-white",
                )}
              >
                <span className="inline-flex items-center gap-2">
                  <Home className="h-4 w-4" />
                  总览与导入
                </span>
                <Badge variant={active === "overview" ? "secondary" : "outline"}>Home</Badge>
              </button>
              {status.services.map((service) => {
                const Icon = serviceMeta[service.key]?.icon ?? Server;
                return (
                  <button
                    type="button"
                    key={service.key}
                    onClick={() => setActive(service.key)}
                    className={cn(
                      "flex items-center justify-between rounded-md px-3 py-2 text-left text-sm transition",
                      active === service.key ? "bg-white text-slate-950" : "text-slate-300 hover:bg-white/10 hover:text-white",
                    )}
                  >
                    <span className="inline-flex items-center gap-2">
                      <Icon className="h-4 w-4" />
                      {service.name}
                    </span>
                    <span className={cn("h-2 w-2 rounded-full", service.ready ? "bg-emerald-400" : "bg-amber-400")} />
                  </button>
                );
              })}
            </nav>

            <div className="mt-auto rounded-lg border border-white/10 bg-white/[0.03] p-3 text-xs text-slate-400">
              <div className="flex items-center gap-2 text-slate-200">
                <LockKeyhole className="h-4 w-4" />
                浏览器锁：{status.browser_lock ? "占用中" : "空闲"}
              </div>
              <p className="mt-2 leading-5">所有需要浏览器的任务会排队执行，避免小红书、X、抖音同时抢 Chromium。</p>
            </div>
          </div>
        </aside>

        <main className="console-grid min-w-0">
          <header className="sticky top-0 z-10 flex min-h-16 items-center justify-between border-b bg-background/90 px-5 backdrop-blur">
            <div>
              <div className="text-sm text-muted-foreground">统一下载控制台</div>
              <h1 className="text-xl font-semibold tracking-normal">{activeService?.name ?? "总览与导入"}</h1>
            </div>
            <div className="flex items-center gap-2">
              <Badge variant={readyCount === status.services.length ? "success" : "warning"}>
                服务 {readyCount}/{status.services.length || 4}
              </Badge>
              <Button variant="outline" size="sm" onClick={refresh} disabled={loading}>
                {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                刷新
              </Button>
            </div>
          </header>

          {active === "overview" ? (
            <div className="grid gap-5 p-5">
              <section className="grid gap-5 xl:grid-cols-[1.4fr_.6fr]">
                <Card className="overflow-hidden border-slate-200 bg-white/95 shadow-panel">
                  <CardHeader className="pb-3">
                    <div className="flex flex-wrap items-start justify-between gap-4">
                      <div>
                        <CardTitle className="text-2xl">一屏管理四个下载器</CardTitle>
                        <CardDescription className="mt-2 max-w-2xl">
                          React + shadcn 风格控制台。左侧切换服务，右侧处理 Cookie、状态、日志和原服务页面。
                        </CardDescription>
                      </div>
                      <Badge variant="success" className="gap-1">
                        <CheckCircle2 className="h-3.5 w-3.5" />
                        {status.version || "v1.5.1-dev"}
                      </Badge>
                    </div>
                  </CardHeader>
                  <CardContent className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                    {status.services.map((service) => {
                      const Icon = serviceMeta[service.key]?.icon ?? Server;
                      return (
                        <button
                          key={service.key}
                          type="button"
                          onClick={() => setActive(service.key)}
                          className="group rounded-lg border bg-card p-4 text-left shadow-sm transition hover:-translate-y-0.5 hover:border-teal-300 hover:shadow-panel"
                        >
                          <div className="flex items-center justify-between gap-3">
                            <Icon className={cn("h-5 w-5", serviceMeta[service.key]?.tone)} />
                            <Badge variant={service.ready ? "success" : "warning"}>{service.ready ? "已就绪" : "启动中"}</Badge>
                          </div>
                          <div className="mt-4 text-base font-semibold">{service.name}</div>
                          <p className="mt-1 min-h-10 text-sm leading-5 text-muted-foreground">{serviceMeta[service.key]?.description}</p>
                          <div className="mt-3 inline-flex items-center gap-1 text-xs font-semibold text-teal-700">
                            打开工作区 <ArrowUpRight className="h-3.5 w-3.5 transition group-hover:translate-x-0.5 group-hover:-translate-y-0.5" />
                          </div>
                        </button>
                      );
                    })}
                  </CardContent>
                </Card>

                <Card className="shadow-panel">
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2">
                      <Gauge className="h-5 w-5 text-teal-700" />
                      运行概况
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="grid gap-3">
                    <Metric label="服务就绪" value={`${readyCount}/${status.services.length || 4}`} icon={Server} />
                    <Metric label="浏览器锁" value={status.browser_lock ? "占用中" : "空闲"} icon={LockKeyhole} />
                    <Metric label="子进程" value={`${status.processes.length}`} icon={Activity} />
                    <Metric label="最近日志" value={`${status.logs.length}`} icon={Clock3} />
                  </CardContent>
                </Card>
              </section>

              <section className="grid gap-5 xl:grid-cols-[1.05fr_.95fr]">
                <Card className="shadow-panel">
                  <CardHeader>
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <CardTitle>Cookie 导入</CardTitle>
                        <CardDescription>支持 cookies.txt、Cookie Header、抖音 app.yaml 的 cookie 段。预览不显示明文。</CardDescription>
                      </div>
                      <FileInput className="h-5 w-5 text-muted-foreground" />
                    </div>
                  </CardHeader>
                  <CardContent>
                    <form className="grid gap-4" onSubmit={previewCookies}>
                      <div className="grid gap-3 lg:grid-cols-[1fr_.85fr]">
                        <div className="grid gap-3">
                          <label className="grid gap-2 text-sm font-medium">
                            上传 cookies.txt
                            <Input name="cookie_file" type="file" accept=".txt,.cookies,text/plain" />
                          </label>
                          <label className="grid gap-2 text-sm font-medium">
                            粘贴 Cookie 内容
                            <Textarea name="cookie_text" placeholder="cookie: sessionid=...; ttwid=..." />
                          </label>
                        </div>
                        <div className="grid content-start gap-2">
                          {targets.map((target) => (
                            <label
                              key={target.key}
                              className="flex cursor-pointer items-start gap-3 rounded-lg border bg-muted/30 p-3 text-sm transition hover:bg-muted"
                            >
                              <input
                                className="mt-1 h-4 w-4 accent-teal-700"
                                type="checkbox"
                                checked={selectedTargets.has(target.key)}
                                onChange={(event) => {
                                  const next = new Set(selectedTargets);
                                  if (event.target.checked) next.add(target.key);
                                  else next.delete(target.key);
                                  setSelectedTargets(next);
                                }}
                              />
                              <span>
                                <span className="block font-semibold">{target.label}</span>
                                <span className="block break-all text-xs leading-5 text-muted-foreground">{target.output}</span>
                              </span>
                            </label>
                          ))}
                        </div>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        <Button type="submit" variant="secondary" disabled={busy !== ""}>
                          {busy === "preview" ? <Loader2 className="h-4 w-4 animate-spin" /> : <ClipboardCheck className="h-4 w-4" />}
                          预览差异
                        </Button>
                        <Button type="button" disabled={busy !== ""} onClick={(event) => importCookies(event.currentTarget.form!)}>
                          {busy === "import" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
                          导入勾选项目
                        </Button>
                      </div>
                    </form>
                    {message ? <div className="mt-4 rounded-md border bg-muted p-3 text-sm">{message}</div> : null}
                    <PreviewGrid preview={preview} />
                  </CardContent>
                </Card>

                <Card className="shadow-panel">
                  <CardHeader>
                    <CardTitle>集成日志</CardTitle>
                    <CardDescription>长行自动换行，方便看 Cookie 导入、子服务启动和浏览器锁状态。</CardDescription>
                  </CardHeader>
                  <CardContent>
                    <pre className="log-scroll max-h-[520px] overflow-auto whitespace-pre-wrap break-words rounded-md bg-slate-950 p-4 text-xs leading-5 text-slate-100">
                      {logs || "暂无日志"}
                    </pre>
                  </CardContent>
                </Card>
              </section>
            </div>
          ) : (
            <ServiceWorkspace service={activeService} />
          )}
        </main>
      </div>
    </div>
  );
}

function Metric({ label, value, icon: Icon }: { label: string; value: string; icon: typeof Activity }) {
  return (
    <div className="flex items-center gap-3 rounded-lg border bg-muted/40 p-3">
      <div className="grid h-9 w-9 place-items-center rounded-md bg-white text-teal-700 shadow-sm">
        <Icon className="h-4 w-4" />
      </div>
      <div>
        <div className="text-xs text-muted-foreground">{label}</div>
        <div className="text-lg font-semibold">{value}</div>
      </div>
    </div>
  );
}

function PreviewGrid({ preview }: { preview: PreviewPayload | null }) {
  const items = preview ? Object.values(preview.targets) : [];
  if (!preview) {
    return <p className="mt-4 text-sm text-muted-foreground">预览后会显示字段数量、新增、变化、缺失关键字段。</p>;
  }
  return (
    <div className="mt-4 grid gap-3">
      {items.map((item) => {
        const missing = item.missing_required?.length > 0;
        const recognized = item.incoming_count > 0;
        return (
          <div key={item.key} className="rounded-lg border bg-card p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="font-semibold">{item.name}</div>
              <Badge variant={!recognized ? "warning" : missing ? "danger" : "success"}>
                {!recognized ? "未识别" : missing ? "关键字段不足" : "可导入"}
              </Badge>
            </div>
            <div className="mt-3 grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
              <MiniStat label="导入" value={item.incoming_count} />
              <MiniStat label="现有" value={item.existing_count} />
              <MiniStat label="新增" value={item.added_count} />
              <MiniStat label="变化" value={item.changed_count} />
            </div>
            <div className="mt-3 grid gap-1 text-xs leading-5 text-muted-foreground">
              <div>导入字段：{compactNames(item.incoming_names)}</div>
              <div>缺少关键字段：{compactNames(item.missing_required)}</div>
              <div>变化字段：{compactNames(item.changed_names)}</div>
              <div>现有但本次没有：{compactNames(item.removed_names)}</div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function MiniStat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md bg-muted/50 p-2">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="text-base font-semibold">{value}</div>
    </div>
  );
}

function ServiceWorkspace({ service }: { service?: Service }) {
  const { data, loading, error, refresh, runAction } = useServiceStatus(service);
  if (!service) {
    return <div className="p-5 text-muted-foreground">服务信息加载中...</div>;
  }
  const Icon = serviceMeta[service.key]?.icon ?? Server;
  const logs = Array.isArray(data?.logs) ? (data.logs as unknown[]).slice(-100).join("\n") : "";
  const runtime = typeof data?.runtime === "object" && data.runtime ? (data.runtime as Record<string, unknown>) : {};
  const progress = typeof data?.progress === "object" && data.progress ? (data.progress as Record<string, unknown>) : {};
  const stats = buildServiceStats(service.key, data, runtime, progress);
  return (
    <div className="grid min-h-[calc(100vh-4rem)] gap-4 p-5">
      <Card className="shadow-panel">
        <CardContent className="flex flex-wrap items-center justify-between gap-3 p-4">
          <div className="flex items-center gap-3">
            <div className="grid h-10 w-10 place-items-center rounded-md bg-muted">
              <Icon className={cn("h-5 w-5", serviceMeta[service.key]?.tone)} />
            </div>
            <div>
              <div className="font-semibold">{service.name}</div>
              <div className="text-sm text-muted-foreground">{serviceMeta[service.key]?.description}</div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant={service.ready ? "success" : "warning"}>{service.ready ? "已就绪" : "启动中"}</Badge>
            <Button variant="outline" size="sm" onClick={refresh} disabled={loading}>
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
              刷新状态
            </Button>
            <Button variant="outline" size="sm" asChild>
              <a href={service.path} target="_blank" rel="noreferrer">
                新窗口 <ArrowUpRight className="h-4 w-4" />
              </a>
            </Button>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-4 xl:grid-cols-[.95fr_1.05fr]">
        <Card className="shadow-panel">
          <CardHeader>
            <CardTitle>React 状态面板</CardTitle>
            <CardDescription>统一读取子服务 API，快捷操作会走原服务接口，兼容旧 worker。</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4">
            {error ? <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">状态读取失败：{error}</div> : null}
            <div className="grid gap-3 sm:grid-cols-2">
              {stats.map((stat) => (
                <Metric key={stat.label} label={stat.label} value={stat.value} icon={stat.icon} />
              ))}
            </div>
            <div className="flex flex-wrap gap-2">
              {(serviceActions[service.key] || []).map((action) => (
                <Button
                  key={action.path}
                  variant={action.variant || "default"}
                  size="sm"
                  disabled={loading || !service.ready}
                  onClick={() => runAction(action.path)}
                >
                  {action.variant === "destructive" ? <Square className="h-4 w-4" /> : <PlayCircle className="h-4 w-4" />}
                  {action.label}
                </Button>
              ))}
            </div>
            <pre className="log-scroll max-h-[360px] overflow-auto whitespace-pre-wrap break-words rounded-md bg-slate-950 p-4 text-xs leading-5 text-slate-100">
              {logs || "暂无子服务日志，或服务还未就绪。"}
            </pre>
          </CardContent>
        </Card>

        <Card className="shadow-panel">
          <CardHeader>
            <CardTitle>高级设置</CardTitle>
            <CardDescription>保留原页面作为兼容入口，复杂表单和特殊流程仍可直接使用。</CardDescription>
          </CardHeader>
          <CardContent className="h-[620px] p-0">
            <iframe title={`${service.name} 管理页面`} src={service.path} className="h-full w-full rounded-b-lg border-0 bg-white" />
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function textValue(value: unknown, fallback = "-") {
  if (value === null || value === undefined || value === "") return fallback;
  if (typeof value === "boolean") return value ? "是" : "否";
  if (typeof value === "number") return String(value);
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

function buildServiceStats(
  key: string,
  data: Record<string, unknown> | null,
  runtime: Record<string, unknown>,
  progress: Record<string, unknown>,
): { label: string; value: string; icon: typeof Activity }[] {
  if (!data) {
    return [
      { label: "状态", value: "等待刷新", icon: Clock3 },
      { label: "日志", value: "0", icon: Activity },
    ];
  }
  if (key === "xhs") {
    const db = typeof data.database === "object" && data.database ? (data.database as Record<string, unknown>) : {};
    const cfg = typeof data.config === "object" && data.config ? (data.config as Record<string, unknown>) : {};
    return [
      { label: "运行中", value: textValue(runtime.is_running), icon: Activity },
      { label: "总作品", value: textValue(db.total_notes), icon: Database },
      { label: "自动运行", value: textValue(cfg.auto_run_enabled), icon: ShieldCheck },
      { label: "浏览器采集", value: textValue(cfg.browser_enabled), icon: Server },
    ];
  }
  if (key === "douyin") {
    const version = typeof data.version === "object" && data.version ? (data.version as Record<string, unknown>) : {};
    return [
      { label: "运行中", value: textValue(data.running), icon: Activity },
      { label: "任务数", value: textValue(data.jobs_count), icon: PlayCircle },
      { label: "f2 当前", value: textValue(version.current), icon: ShieldCheck },
      { label: "f2 状态", value: textValue(version.status), icon: Gauge },
    ];
  }
  return [
    { label: "运行中", value: textValue(data.running ?? runtime.is_running), icon: Activity },
    { label: "下次运行", value: textValue(data.next_run_at ?? runtime.next_run_at), icon: Clock3 },
    { label: "待处理", value: textValue(progress.pending ?? data.pending ?? data.discovered), icon: Database },
    { label: "已下载", value: textValue(progress.downloaded ?? data.downloaded), icon: CheckCircle2 },
  ];
}

export default App;
