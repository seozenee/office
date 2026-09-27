export type TaskStatus = "BACKLOG" | "PLANNED" | "RESEARCHING" | "ANALYZING" | "WRITING" | "REVIEWING" | "WAITING_USER" | "DONE" | "FAILED";

export interface Employee {
  id: number; name: string; department: string; title: string; role: string; agent_type: string; is_lead: boolean;
  persona: string; appearance: { hair: string; skin: string; shirt: string; style: number }; desk: { x: number; y: number };
  status: "idle" | "working" | "meeting" | "away"; status_text: string; current_task_id: number | null;
}
export interface Room { key: string; name: string; x: number; y: number; w: number; h: number; floor: string; accent: string }
export interface Layout { map: { width: number; height: number; tile: number }; rooms: Room[]; departments: Record<string, string>; employees: Employee[] }
export interface Message {
  id: number; channel_id: number; sender_type: "user" | "employee" | "system"; sender_id: number | null; recipient_id: number | null;
  content: string; kind: string; task_id: number | null; meta: Record<string, unknown>; created_at: string;
}
export interface Channel { id: number; kind: string; name: string; department: string | null; employee_id: number | null }
export interface Step { id: number; name: string; agent: string; employee_id: number | null; status: string; detail: string; started_at: string | null; finished_at: string | null }
export interface ArtifactVersion { id: number; version: number; label: string; format: string; file_name: string; change_note: string; size_bytes: number; created_at: string }
export interface Artifact { id: number; kind: string; title: string; status: string; author_agent: string; version: number; task_id: number | null; project_id: number | null; versions: ArtifactVersion[]; created_at: string }
export interface ApprovalStep { approver: string; employee_id: number | null; status: string; note: string | null; at: string | null }
export interface Approval { id: number; title: string; action: string; risk_level: string; status: string; line: ApprovalStep[]; requires_user: boolean; task_id: number | null; payload: Record<string, unknown>; decision_note: string | null; created_at: string }
export interface Meeting { id: number; title: string; task_id: number | null; agenda: string[]; participant_ids: number[]; status: string; decisions: string[]; minutes: string; created_at: string; action_items: ActionItem[]; transcript?: Message[] }
export interface ActionItem { id: number; decision: string; description: string; owner: string; deadline: string | null; status: string }
export interface Task {
  id: number; title: string; request: string; status: TaskStatus; priority: number; deadline: string | null; owner: string; project_id: number | null;
  progress: number; current_step: string; agents: string[]; error: string | null; created_at: string; updated_at: string;
  plan?: Record<string, any>; result_summary?: Record<string, any>; steps?: Step[]; artifacts?: Artifact[]; approvals?: Approval[]; meetings?: Meeting[];
  counts?: { sources: number; sources_accessed: number; claims: number; verified: number };
}
export interface Source { id: number; title: string; url: string | null; publisher: string | null; source_type: string; tier: number; publication_date: string | null; access_date: string; accessed: boolean; access_error: string | null; task_id: number | null; snippet: string; query: string | null }
export interface Claim { id: number; text: string; kind: string; topic: string | null; source_id: number | null; supporting_quote: string | null; page_number: number | null; confidence: number; verification_status: string; verification_notes: string[]; corroborating_source_ids: number[] }
export interface CitationCard { number: number; source_id: number; title: string; publisher: string | null; date: string | null; url: string | null; type: string; tier: number; accessed: string | null; passages: { claim_id: number; page: number | null; passage: string; claim: string; confidence: number; status?: string }[] }
export interface Project { id: number; name: string; slug: string; description: string; context: string; created_at: string }
export interface KBDoc { id: number; title: string; filename: string | null; mime: string; source_url: string | null; author: string | null; date: string | null; page_count: number; is_ocr: boolean; injection_flags: string[]; project_id: number | null; tables: number; sections_count: number; references: number; created_at: string }
export interface Notification { id: number; title: string; body: string; task_id: number | null; link: string | null; read: boolean; created_at: string }
export interface AuditEntry { id: number; ts: string; actor: string; action: string; target_type: string | null; target_id: number | null; task_id: number | null; risk: string; detail: Record<string, unknown> }
