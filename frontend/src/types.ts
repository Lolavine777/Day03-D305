export type AgentMode = "auto" | "level1" | "level2" | "level3" | "level4";

export type TraceKind =
  | "thought"
  | "action"
  | "observation"
  | "guardrail"
  | "final"
  | "system";

export interface Property {
  property_id: string;
  title?: string;
  address?: string;
  city?: string;
  district?: string;
  ward?: string;
  price_vnd?: number;
  monthly_rent_vnd?: number;
  price?: number;
  area_m2?: number;
  area?: number;
  property_type?: string;
  amenities?: string[];
  deposit_months?: number;
  available?: boolean;
  description?: string;
}

export interface ViewingSlot {
  slot_id: string;
  property_id: string;
  starts_at?: string;
  start_time?: string;
  date?: string;
  time?: string;
  available?: boolean;
}

export interface Booking {
  booking_id: string;
  property_id: string;
  slot_id: string;
  starts_at?: string;
  viewer_name?: string;
  masked_phone?: string;
  phone_masked?: string;
  viewer_phone?: string;
  status?: string;
  created_at?: string;
}

export interface TraceEntry {
  id?: string;
  type?: TraceKind | string;
  kind?: TraceKind | string;
  label?: string;
  content?: unknown;
  message?: string;
  tool?: string;
  args?: Record<string, unknown>;
  result?: unknown;
  iteration?: number;
  step?: number;
  ok?: boolean;
  code?: string;
  data?: unknown;
}

export interface ToolCall {
  tool?: string;
  name?: string;
  args?: Record<string, unknown>;
  result?: unknown;
  ok?: boolean;
}

export interface ConfirmationContext {
  accepted: true;
  property_id: string;
  slot_id: string;
  viewer_name: string;
  viewer_phone: string;
}

export interface CreateSessionResponse {
  session_id: string;
}

export interface ChatRequest {
  session_id: string;
  message: string;
  mode: AgentMode;
  confirmation?: ConfirmationContext;
}

export interface ChatResponse {
  session_id?: string;
  answer: string;
  mode_used: AgentMode | string;
  status: string;
  stop_reason: string;
  trace?: TraceEntry[];
  tool_calls?: ToolCall[];
  properties?: Property[];
  slots?: ViewingSlot[];
  booking?: Booking | null;
  requires_confirmation?: boolean;
}

export interface BookingsResponse {
  bookings: Booking[];
}

export interface ChatMessage {
  id: string;
  role: "assistant" | "user";
  content: string;
  mode?: string;
  stopReason?: string;
}
