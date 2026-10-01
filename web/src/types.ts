export type QuizStatus = "draft" | "active" | "completed";
export type RoundStatus = "pending" | "open" | "closed";

export interface Question {
  options: string[];
  prompt: string;
}

export interface QuizRound {
  closes_at: string | null;
  id: string;
  opens_at: string | null;
  question: Question;
  status: RoundStatus;
}

export interface QuizSnapshot {
  current_round: QuizRound | null;
  id: string;
  status: QuizStatus;
}

export interface LeaderboardEntry {
  display_name: string;
  participant_id: string;
  rank: number;
  total_response_ms: number;
  total_score: number;
}

export interface LeaderboardPage {
  entries: LeaderboardEntry[];
  limit: number;
  offset: number;
  total: number;
}

export interface JoinResponse {
  participant_id: string;
  participant_token: string;
  quiz_id: string;
  stream_url: string;
}

export interface AnswerResult {
  awarded_points: number;
  is_correct: boolean;
  is_replay: boolean;
  response_ms: number;
  submission_id: string;
  total_response_ms: number;
  total_score: number;
}

export interface RoundTransition {
  closes_at: string;
  opens_at: string;
  round_id: string;
  status: RoundStatus;
}

export interface AdvanceRoundResult {
  closed_round_id: string;
  completed: boolean;
  next_round: RoundTransition | null;
}

export interface QuizResetResult {
  removed_participants: number;
  status: QuizStatus;
}

export interface SnapshotEvent {
  current_round: QuizRound | null;
  event_version: 1;
  quiz_id: string;
  seq: number;
  status: QuizStatus;
}

export interface RoundEventPayload {
  closes_at: string;
  event_version: 1;
  opens_at: string;
  round_id: string;
  status: RoundStatus;
}

export interface LeaderboardEventPayload {
  event_version: 1;
  standings: LeaderboardEntry[];
  total_participants: number;
}

export interface QuizEvent<TPayload> {
  event_version: 1;
  occurred_at: string;
  payload: TPayload;
  quiz_id: string;
  seq: number;
  type: "answer.accepted" | "round.opened" | "round.closed" | "leaderboard.updated";
}
