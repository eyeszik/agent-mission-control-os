/**
 * Pure parts of `agency/project_os/video.py`: the governed bridge from the
 * cinematic compiler to FreeVideoForge and back into the project graph.
 *
 * Left in Python, because they run the cinematic pipeline or touch the
 * machine: `freevideoforge_capability` (looks for a package, Pillow, ffmpeg
 * and ffprobe), the `run_pipeline(...)` call inside `plan_video_production`,
 * and the file reads/hashing inside `read_freevideoforge_output`. The twin
 * takes their results as input: a snapshot of the pipeline result, the
 * capability report, and the run directory's parsed documents and file
 * digests. Parse JSON documents with `parseTokenJson` from
 * `@amc/design-tokens` so int and float stay distinct (the hashes depend on it).
 *
 * Nothing here renders, publishes or spends: `allow_paid` is the literal
 * `false` in every request, and a QC result is never `PASS`
 * (`PASS_OR_NOT_VERIFIED` at best).
 */
import { CanonicalFloat } from '@amc/canonical';
import { ReproducibilityRecordSchema } from '@amc/shared';
import { compareCodePoints, pyStr } from '@amc/kernel';
import { VideoBridgeError } from './errors';
import { canonicalSha256, type PyJson } from './json';
import { sliceCodePoints, stripChar, strOf, truthy } from './pytext';
import { pyRepr } from '@amc/kernel';

export const VIDEO_PIPELINE_STAGES = [
  'IDEA', 'RESEARCH', 'PREMISE', 'CHARACTER_BIBLE', 'WORLD_BIBLE', 'TREATMENT', 'SCRIPT', 'BEAT_SHEET',
  'SCENES', 'STORYBOARD', 'PREVIZ', 'SHOT_LIST', 'SHOT_IR', 'PROMPT_COMPILE', 'PROVIDER_ROUTE', 'GENERATION',
  'INGEST', 'VOICE', 'MUSIC', 'SOUND', 'EDIT', 'MOTION_VFX', 'COLOR', 'CAPTIONS', 'QC', 'MASTER',
  'PLATFORM_VARIANTS', 'THUMBNAILS', 'DISTRIBUTION', 'ARCHIVE',
] as const;

// Stages the cinematic compiler completes before its generation firewall.
const CINEMATIC_STAGES = new Set(['PREMISE', 'CHARACTER_BIBLE', 'WORLD_BIBLE', 'SCENES', 'STORYBOARD', 'SHOT_LIST', 'SHOT_IR', 'PROMPT_COMPILE']);
// Stages FreeVideoForge performs in one local run.
const FVF_STAGES = new Set(['GENERATION', 'VOICE', 'MUSIC', 'EDIT', 'CAPTIONS', 'QC', 'MASTER', 'THUMBNAILS']);

/** FreeVideoForge's output contract: file name -> [mime type, subtype]. */
export const FVF_OUTPUTS: Readonly<Record<string, readonly [string, string]>> = {
  'final.mp4': ['video/mp4', 'video_master'],
  'thumbnail.jpg': ['image/jpeg', 'thumbnail'],
  'script.json': ['application/json', 'video_script'],
  'storyboard.json': ['application/json', 'storyboard'],
  'captions.srt': ['application/x-subrip', 'captions'],
  'manifest.json': ['application/json', 'provenance'],
  'quality-report.json': ['application/json', 'video_qc'],
};

export const FVF_REQUEST_FIELDS = [
  'topic', 'brief', 'duration', 'aspect', 'preset', 'style', 'scenes', 'fps', 'height', 'voice', 'music', 'seed',
  'language', 'burn_captions', 'output_dir', 'run_id', 'allow_paid', 'script_provider', 'speech_provider', 'quality_preset',
] as const;

// sorted() order of the Python set, i.e. by code point
const ASPECTS = ['16:9', '1:1', '4:5', '9:16'];

type Json = Readonly<Record<string, PyJson>>;

/** `value or {}` for a dict-valued field. */
function dict(value: PyJson | undefined): Json {
  return truthy(value) && typeof value === 'object' && !Array.isArray(value) ? (value as Json) : {};
}

function list(value: PyJson | undefined): readonly PyJson[] {
  return truthy(value) && Array.isArray(value) ? (value as readonly PyJson[]) : [];
}

// -- plan ---------------------------------------------------------------------------

/** What the cinematic pipeline returned, reduced to the fields the bridge reads. */
export interface CinematicSnapshot {
  readonly generative: boolean;
  readonly generation_firewall: string;
  readonly mode: string;
  readonly storyboard_count: number;
  readonly unresolved: readonly string[];
  readonly prompts: readonly Json[];
  readonly project: { readonly shots: readonly Json[]; readonly meta: Json; readonly story: Json } | null;
}

/** The part of `freevideoforge_capability()` the plan reads. */
export interface RendererCapability {
  readonly can_render: boolean;
  readonly [key: string]: PyJson;
}

function promptsByShot(prompts: readonly Json[]): Map<string, string> {
  const byShot = new Map<string, string>();
  for (const data of prompts) {
    const shotId = strOf(truthy(data.shot_id) ? data.shot_id : truthy(data.ref) ? data.ref : '');
    const text = truthy(data.text) ? data.text : truthy(data.prompt) ? data.prompt : '';
    if (shotId && truthy(text)) byShot.set(shotId, text as string);
  }
  return byShot;
}

function shotMeta(data: Json, prompts: ReadonlyMap<string, string>): Json {
  const camera = dict(data.camera);
  return {
    shot_id: data.id ?? null,
    scene_id: dict(data.location).scene_id ?? null,
    character_state: dict(data.character_state),
    start_state: dict(data.start_frame),
    end_state: dict(data.final_frame),
    camera: { size: data.shot_size ?? null, angle: data.angle ?? null, ...camera },
    lens: data.lens ?? null,
    movement: (truthy(camera.move) ? camera.move : camera.movement) ?? null,
    lighting: dict(data.light),
    environment: { location: dict(data.location), atmosphere: dict(data.atmosphere) },
    performance: dict(data.performance),
    dialogue: data.dialogue ?? null,
    duration: data.duration ?? null,
    references: [...list(data.identity_refs)],
    prompt: prompts.get(strOf(data.id)) ?? null,
    model_profile: 'portable',
    seed: null,
    generation_refs: [],
    continuity_refs: dict(data.continuity),
    qc: { failure_risks: [...list(data.failure_risks)] },
  };
}

function numeric(value: PyJson | undefined): number | undefined {
  if (typeof value === 'number') return value;
  if (typeof value === 'boolean') return Number(value);
  if (value instanceof CanonicalFloat) return value.value;
  return typeof value === 'bigint' ? Number(value) : undefined;
}

function stageStatus(stage: string, cinematic: CinematicSnapshot, canRender: boolean): string {
  if (CINEMATIC_STAGES.has(stage)) return cinematic.generative ? 'COMPLETE' : 'SKIPPED_NON_GENERATIVE';
  if (stage === 'PROVIDER_ROUTE') return canRender ? 'ROUTED_LOCAL' : 'BLOCKED_NO_LOCAL_RENDERER';
  if (FVF_STAGES.has(stage)) return canRender ? 'PENDING_LOCAL_RENDER' : 'BLOCKED_NO_LOCAL_RENDERER';
  if (stage === 'INGEST') return 'AWAITING_RENDER_OUTPUT';
  return stage === 'DISTRIBUTION' ? 'VIA_PUBLICATION_PIPELINE' : 'MANUAL_OR_NOT_COVERED';
}

function totalSeconds(requested: number | undefined, shots: readonly Json[]): number {
  if (requested) return requested;
  const seconds = shots.reduce((sum, shot) => sum + (numeric(shot.duration) ?? 0), 0);
  return seconds >= 3.0 && seconds <= 600.0 ? seconds : 30.0;
}

function title(meta: Json, request: Json): string {
  const fallback = truthy(request.text) ? request.text : 'Untitled film';
  return sliceCodePoints(strOf(truthy(meta.title) ? meta.title : fallback), 120);
}

function brief(story: Json): string {
  const beats = list(story.scenes).flatMap((scene) => list(dict(scene).beats).map((beat) => dict(beat).summary)).filter(truthy);
  return sliceCodePoints(beats.join(' '), 4000) || strOf(truthy(story.logline) ? story.logline : '');
}

export interface VideoPlan {
  readonly title: string;
  readonly generation_firewall: string;
  readonly cinematic_mode: string;
  readonly shots: readonly Json[];
  readonly storyboard_panels: number;
  readonly unresolved: readonly string[];
  readonly freevideoforge_request: Json;
  readonly renderer: RendererCapability;
  readonly stages: readonly { readonly stage: string; readonly status: string }[];
  readonly plan_hash: string;
}

export interface PlanVideoArgs {
  readonly cinematic_request: Json;
  readonly cinematic: CinematicSnapshot;
  readonly capability: RendererCapability;
  readonly aspect?: string;
  readonly duration?: number | null;
  readonly seed?: number | null;
}

/** `plan_video_production` with the pipeline run and the capability probe already done. */
export function planVideoProduction(args: PlanVideoArgs): VideoPlan {
  const aspect = args.aspect ?? '9:16';
  if (!ASPECTS.includes(aspect)) throw new VideoBridgeError(`aspect must be one of ${pyStr(ASPECTS)}`);
  const { cinematic, capability } = args;
  const prompts = promptsByShot(cinematic.prompts);
  const shots = (cinematic.project?.shots ?? []).map((shot) => shotMeta(shot, prompts));
  const meta = cinematic.project?.meta ?? {};
  const story = cinematic.project?.story ?? {};
  const request: Json = {
    topic: title(meta, args.cinematic_request),
    brief: brief(story),
    duration: new CanonicalFloat(totalSeconds(args.duration ?? undefined, shots)),
    aspect,
    scenes: Math.max(1, Math.min(shots.length || 1, 60)),
    seed: args.seed ?? null,
    allow_paid: false,
  };
  return {
    title: request.topic as string,
    generation_firewall: cinematic.generation_firewall,
    cinematic_mode: cinematic.mode,
    shots,
    storyboard_panels: cinematic.storyboard_count,
    unresolved: [...cinematic.unresolved],
    freevideoforge_request: request,
    renderer: capability,
    stages: VIDEO_PIPELINE_STAGES.map((stage) => ({ stage, status: stageStatus(stage, cinematic, capability.can_render) })),
    plan_hash: canonicalSha256({ request, shots } as unknown as PyJson),
  };
}

// -- reading a finished run -----------------------------------------------------------

export interface FileDigest {
  readonly sha256: string;
  readonly bytes: number;
}

export interface RunFile extends FileDigest {
  readonly path: string;
  readonly mime_type: string;
  readonly subtype: string;
}

export interface ReadRunArgs {
  readonly output_dir: string;
  /** Digests of the files present in the run directory. */
  readonly files: Readonly<Record<string, FileDigest>>;
  /** The run's parsed JSON documents by file name (`manifest.json`, `quality-report.json`, `storyboard.json`). */
  readonly documents: Readonly<Record<string, PyJson>>;
}

const REQUIRED_MANIFEST_KEYS = ['run_id', 'version', 'config_hash', 'providers', 'assets', 'environment'] as const;

function assertRunIsComplete(args: ReadRunArgs, manifest: Json): void {
  const missing = Object.keys(FVF_OUTPUTS).filter((name) => !Object.hasOwn(args.files, name));
  if (missing.length > 0) throw new VideoBridgeError(`not a complete FreeVideoForge run: missing ${missing.join(', ')}`);
  for (const key of REQUIRED_MANIFEST_KEYS) {
    if (!Object.hasOwn(manifest, key)) throw new VideoBridgeError(`manifest.json lacks required key ${pyRepr(key)}`);
  }
  if (manifest.zero_paid_api_spend !== true) {
    throw new VideoBridgeError('run did not certify zero paid-API spend; refusing to ingest as a local render');
  }
}

function runFiles(args: ReadRunArgs): Record<string, RunFile> {
  const dir = stripChar(args.output_dir, '/', 'end');
  return Object.fromEntries(
    Object.entries(FVF_OUTPUTS).map(([name, [mime, subtype]]) => {
      const digest = args.files[name] as FileDigest;
      return [name, { path: `${dir}/${name}`, sha256: digest.sha256, bytes: digest.bytes, mime_type: mime, subtype }];
    }),
  );
}

function reproducibility(manifest: Json, project: Json, files: Record<string, RunFile>) {
  const seeds = [...new Set(list(manifest.assets).map((a) => dict(a).seed).filter((s): s is number => typeof s === 'number'))].sort((a, b) => a - b);
  const models = Object.values(dict(manifest.providers)).filter((v): v is string => typeof v === 'string').sort(compareCodePoints);
  return ReproducibilityRecordSchema.parse({
    subject_ref: `freevideoforge:${strOf(manifest.run_id)}`,
    source_hashes: ['script.json', 'storyboard.json'].map((name) => (files[name] as RunFile).sha256).sort(compareCodePoints),
    prompt_hashes: [],
    schema_version: strOf(manifest.version),
    provider: 'freevideoforge',
    model: models.join(',') || null,
    seed: seeds.length === 1 ? (seeds[0] as number) : null,
    generation_config_hash: truthy(manifest.config_hash) ? strOf(manifest.config_hash) : null,
    tool_contract_version: strOf(manifest.version),
    environment_signature: canonicalSha256(truthy(manifest.environment) ? (manifest.environment as PyJson) : {}),
    execution_args_hash: canonicalSha256(project),
    input_artifact_refs: [],
    output_hash: (files['final.mp4'] as RunFile).sha256,
    guarantee: seeds.length > 0 ? 'SEEDED_BEST_EFFORT' : 'DETERMINISTIC_PIPELINE',
  });
}

/** `read_freevideoforge_output` once the directory has been read: validates the run against its contract. */
export function readFreevideoforgeOutput(args: ReadRunArgs) {
  const manifest = dict(args.documents['manifest.json']);
  assertRunIsComplete(args, manifest);
  const quality = dict(args.documents['quality-report.json']);
  const storyboard = args.documents['storyboard.json'];
  const files = runFiles(args);
  const project = dict(manifest.project);
  const checks = list(quality.checks);
  const failed = checks.map(dict).filter((c) => c.status === 'FAIL').map((c) => c.name ?? null);
  const scenes = !Array.isArray(storyboard) && typeof storyboard === 'object' && storyboard !== null ? (storyboard as Json).scenes : storyboard;
  const render = dict(project.render);
  return {
    run_id: manifest.run_id as PyJson,
    files,
    qc: { status: failed.length > 0 ? 'FAIL' : 'PASS_OR_NOT_VERIFIED', failed_checks: failed, check_count: checks.length },
    duration_seconds: (truthy(render.duration) ? render.duration : project.duration) ?? null,
    aspect: (truthy(render.aspect) ? render.aspect : project.aspect) ?? null,
    scene_count: Array.isArray(scenes) ? scenes.length : scenes && typeof scenes === 'object' ? Object.keys(scenes).length : 0,
    reproducibility: reproducibility(manifest, project, files),
  };
}

