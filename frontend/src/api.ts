import type {
  Booking,
  BookingsResponse,
  ChatRequest,
  ChatResponse,
  CreateSessionResponse
} from "./types";

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers
    }
  });

  if (!response.ok) {
    let message = `Máy chủ trả về lỗi ${response.status}.`;
    try {
      const errorBody = (await response.json()) as {
        detail?: string | { message?: string };
        message?: string;
      };
      if (typeof errorBody.detail === "string") {
        message = errorBody.detail;
      } else if (errorBody.detail?.message) {
        message = errorBody.detail.message;
      } else if (errorBody.message) {
        message = errorBody.message;
      }
    } catch {
      // Keep the status-based message when the response is not JSON.
    }
    throw new ApiError(message, response.status);
  }

  return (await response.json()) as T;
}

export function createSession(): Promise<CreateSessionResponse> {
  return requestJson<CreateSessionResponse>("/api/sessions", {
    method: "POST",
    body: JSON.stringify({})
  });
}

export function sendChat(payload: ChatRequest): Promise<ChatResponse> {
  return requestJson<ChatResponse>("/api/chat", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function listBookings(sessionId: string): Promise<Booking[]> {
  const response = await requestJson<BookingsResponse | Booking[]>(
    `/api/bookings?session_id=${encodeURIComponent(sessionId)}`
  );
  return Array.isArray(response) ? response : response.bookings;
}

export function bookingExportUrl(sessionId: string): string {
  return `${API_BASE_URL}/api/bookings/export?session_id=${encodeURIComponent(sessionId)}`;
}
