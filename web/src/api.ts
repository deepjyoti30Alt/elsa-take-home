import type {
  AnswerResult,
  JoinResponse,
  LeaderboardPage,
  QuizSnapshot,
  RoundTransition,
} from "./types";

interface ApiErrorBody {
  error?: {
    code?: string;
    correlation_id?: string;
    message?: string;
  };
}

export class ApiError extends Error {
  readonly code: string | undefined;
  readonly correlationId: string | undefined;
  readonly status: number;

  constructor(status: number, body: ApiErrorBody) {
    super(body.error?.message ?? `The API returned HTTP ${status}.`);
    this.code = body.error?.code;
    this.correlationId = body.error?.correlation_id;
    this.name = "ApiError";
    this.status = status;
  }
}

const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL ?? "/api").replace(/\/$/, "");

function apiUrl(path: string): string {
  return `${apiBaseUrl}${path}`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(apiUrl(path), init);
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as ApiErrorBody;
    throw new ApiError(response.status, body);
  }
  return (await response.json()) as T;
}

export function getStreamUrl(streamPath: string): string {
  return apiUrl(streamPath);
}

export function getQuiz(quizId: string): Promise<QuizSnapshot> {
  return request<QuizSnapshot>(`/v1/quizzes/${encodeURIComponent(quizId)}`);
}

export function getLeaderboard(quizId: string): Promise<LeaderboardPage> {
  return request<LeaderboardPage>(
    `/v1/quizzes/${encodeURIComponent(quizId)}/leaderboard?limit=50&offset=0`,
  );
}

export function joinQuiz(quizId: string, displayName: string): Promise<JoinResponse> {
  return request<JoinResponse>(`/v1/quizzes/${encodeURIComponent(quizId)}/participants`, {
    body: JSON.stringify({ display_name: displayName }),
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": crypto.randomUUID(),
    },
    method: "POST",
  });
}

export function submitAnswer(
  quizId: string,
  roundId: string,
  participantToken: string,
  answer: string,
): Promise<AnswerResult> {
  return request<AnswerResult>(
    `/v1/quizzes/${encodeURIComponent(quizId)}/rounds/${encodeURIComponent(roundId)}/answers`,
    {
      body: JSON.stringify({ answer }),
      headers: {
        Authorization: `Bearer ${participantToken}`,
        "Content-Type": "application/json",
      },
      method: "POST",
    },
  );
}

export function openRound(
  quizId: string,
  roundId: string,
  hostToken: string,
  durationSeconds: number,
): Promise<RoundTransition> {
  return request<RoundTransition>(
    `/v1/quizzes/${encodeURIComponent(quizId)}/rounds/${encodeURIComponent(roundId)}/open`,
    {
      body: JSON.stringify({ duration_seconds: durationSeconds }),
      headers: {
        "Content-Type": "application/json",
        "X-Host-Token": hostToken,
      },
      method: "POST",
    },
  );
}

export function closeRound(
  quizId: string,
  roundId: string,
  hostToken: string,
): Promise<RoundTransition> {
  return request<RoundTransition>(
    `/v1/quizzes/${encodeURIComponent(quizId)}/rounds/${encodeURIComponent(roundId)}/close`,
    {
      headers: { "X-Host-Token": hostToken },
      method: "POST",
    },
  );
}
