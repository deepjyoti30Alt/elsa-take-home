import { FormEvent, useCallback, useEffect, useRef, useState } from "react";

import {
  ApiError,
  closeRound,
  getLeaderboard,
  getQuiz,
  getStreamUrl,
  joinQuiz,
  openRound,
  submitAnswer,
} from "./api";
import type {
  AnswerResult,
  LeaderboardEntry,
  LeaderboardEventPayload,
  QuizEvent,
  QuizSnapshot,
  RoundEventPayload,
  SnapshotEvent,
} from "./types";

const DEMO_QUIZ_ID = "10000000-0000-0000-0000-000000000001";
const DEMO_FIRST_ROUND_ID = "30000000-0000-0000-0000-000000000001";

type ConnectionState = "connected" | "connecting" | "disconnected";

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    const suffix = error.correlationId === undefined ? "" : ` (request ${error.correlationId})`;
    return `${error.message}${suffix}`;
  }
  return error instanceof Error ? error.message : "An unexpected error occurred.";
}

function snapshotFromEvent(event: SnapshotEvent): QuizSnapshot {
  return {
    current_round: event.current_round,
    id: event.quiz_id,
    status: event.status,
  };
}

function secondsRemaining(closesAt: string | null, now: number): number | null {
  if (closesAt === null) {
    return null;
  }
  return Math.max(0, Math.ceil((new Date(closesAt).getTime() - now) / 1_000));
}

export function App(): JSX.Element {
  const [quizId, setQuizId] = useState(DEMO_QUIZ_ID);
  const [displayName, setDisplayName] = useState("");
  const [hostToken, setHostToken] = useState("");
  const [hostRoundId, setHostRoundId] = useState(DEMO_FIRST_ROUND_ID);
  const [durationSeconds, setDurationSeconds] = useState(30);
  const [participantToken, setParticipantToken] = useState<string | null>(null);
  const [participantId, setParticipantId] = useState<string | null>(null);
  const [streamPath, setStreamPath] = useState<string | null>(null);
  const [quiz, setQuiz] = useState<QuizSnapshot | null>(null);
  const [leaderboard, setLeaderboard] = useState<LeaderboardEntry[]>([]);
  const [leaderboardTotal, setLeaderboardTotal] = useState(0);
  const [selectedAnswer, setSelectedAnswer] = useState("");
  const [answerResult, setAnswerResult] = useState<AnswerResult | null>(null);
  const [connection, setConnection] = useState<ConnectionState>("disconnected");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState("Join the seeded quiz to start receiving live updates.");
  const [isJoining, setIsJoining] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isHostActionRunning, setIsHostActionRunning] = useState(false);
  const [now, setNow] = useState(Date.now());
  const latestSequence = useRef(-1);

  const refreshPublicState = useCallback(async (id: string) => {
    const [nextQuiz, nextLeaderboard] = await Promise.all([getQuiz(id), getLeaderboard(id)]);
    setQuiz(nextQuiz);
    setLeaderboard(nextLeaderboard.entries);
    setLeaderboardTotal(nextLeaderboard.total);
  }, []);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    setSelectedAnswer("");
    setAnswerResult(null);
  }, [quiz?.current_round?.id]);

  useEffect(() => {
    if (streamPath === null) {
      return undefined;
    }

    const source = new EventSource(getStreamUrl(streamPath));
    setConnection("connecting");
    source.onopen = () => setConnection("connected");
    source.onerror = () => setConnection("connecting");

    const handleSnapshot = (message: MessageEvent<string>) => {
      const event = JSON.parse(message.data) as SnapshotEvent;
      if (event.seq < latestSequence.current) {
        return;
      }
      latestSequence.current = event.seq;
      setQuiz(snapshotFromEvent(event));
    };

    const handleRound = (message: MessageEvent<string>) => {
      const event = JSON.parse(message.data) as QuizEvent<RoundEventPayload>;
      if (event.seq <= latestSequence.current) {
        return;
      }
      latestSequence.current = event.seq;
      void refreshPublicState(event.quiz_id).catch((requestError: unknown) => {
        setError(errorMessage(requestError));
      });
    };

    const handleLeaderboard = (message: MessageEvent<string>) => {
      const event = JSON.parse(message.data) as QuizEvent<LeaderboardEventPayload>;
      if (event.seq <= latestSequence.current) {
        return;
      }
      latestSequence.current = event.seq;
      setLeaderboard(event.payload.standings);
      setLeaderboardTotal(event.payload.total_participants);
    };

    source.addEventListener("quiz.snapshot", handleSnapshot);
    source.addEventListener("round.opened", handleRound);
    source.addEventListener("round.closed", handleRound);
    source.addEventListener("leaderboard.updated", handleLeaderboard);

    return () => {
      source.close();
      setConnection("disconnected");
    };
  }, [refreshPublicState, streamPath]);

  async function handleJoin(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const normalizedName = displayName.trim();
    if (normalizedName.length === 0) {
      setError("Enter a display name before joining.");
      return;
    }

    setError(null);
    setIsJoining(true);
    setStreamPath(null);
    latestSequence.current = -1;
    try {
      const join = await joinQuiz(quizId, normalizedName);
      setParticipantId(join.participant_id);
      setParticipantToken(join.participant_token);
      setStreamPath(join.stream_url);
      await refreshPublicState(join.quiz_id);
      setNotice(`Joined as ${normalizedName}. Your live stream is connected.`);
    } catch (joinError) {
      setParticipantId(null);
      setParticipantToken(null);
      setError(errorMessage(joinError));
    } finally {
      setIsJoining(false);
    }
  }

  async function handleSubmitAnswer(): Promise<void> {
    const round = quiz?.current_round;
    if (participantToken === null || round === undefined || round === null || selectedAnswer === "") {
      return;
    }

    setError(null);
    setIsSubmitting(true);
    try {
      const result = await submitAnswer(quizId, round.id, participantToken, selectedAnswer);
      setAnswerResult(result);
      setNotice(
        result.is_correct
          ? `Correct — ${result.awarded_points} points awarded.`
          : "Not quite. Your answer was recorded; watch the leaderboard update.",
      );
    } catch (submissionError) {
      setError(errorMessage(submissionError));
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleHostAction(action: "open" | "close"): Promise<void> {
    const roundId = action === "close" ? quiz?.current_round?.id : hostRoundId;
    if (hostToken.trim() === "" || roundId === undefined || roundId === "") {
      setError("Enter the host token and a round ID before changing a round.");
      return;
    }

    setError(null);
    setIsHostActionRunning(true);
    try {
      if (action === "open") {
        await openRound(quizId, roundId, hostToken, durationSeconds);
        setNotice("Round opened. Connected participants will receive it through SSE.");
      } else {
        await closeRound(quizId, roundId, hostToken);
        setNotice("Round closed. The final leaderboard event is on its way.");
      }
      await refreshPublicState(quizId);
    } catch (hostError) {
      setError(errorMessage(hostError));
    } finally {
      setIsHostActionRunning(false);
    }
  }

  const activeRound = quiz?.current_round ?? null;
  const timeRemaining = secondsRemaining(activeRound?.closes_at ?? null, now);
  const canSubmit =
    activeRound?.status === "open" &&
    selectedAnswer !== "" &&
    participantToken !== null &&
    !isSubmitting &&
    answerResult === null;

  return (
    <main className="app-shell">
      <header className="hero">
        <div>
          <p className="eyebrow">Real-time vocabulary quiz</p>
          <h1>Vocabulary Live</h1>
          <p className="subtitle">A thin React client for the FastAPI REST and SSE contract.</p>
        </div>
        <span className={`connection connection--${connection}`}>{connection}</span>
      </header>

      {error !== null ? <p className="alert alert--error">{error}</p> : null}
      <p className="alert alert--notice">{notice}</p>

      <section className="setup-grid" aria-label="Quiz setup">
        <form className="panel" onSubmit={handleJoin}>
          <div className="panel-heading">
            <p className="eyebrow">Participant</p>
            <h2>Join the quiz</h2>
          </div>
          <label>
            Quiz ID
            <input value={quizId} onChange={(event) => setQuizId(event.target.value)} required />
          </label>
          <label>
            Display name
            <input
              maxLength={80}
              onChange={(event) => setDisplayName(event.target.value)}
              placeholder="Ada"
              value={displayName}
              required
            />
          </label>
          <button className="button button--primary" disabled={isJoining} type="submit">
            {isJoining ? "Joining…" : participantId === null ? "Join quiz" : "Join as another player"}
          </button>
        </form>

        <section className="panel" aria-label="Host controls">
          <div className="panel-heading">
            <p className="eyebrow">Host demo controls</p>
            <h2>Run a round</h2>
          </div>
          <label>
            Host token
            <input
              onChange={(event) => setHostToken(event.target.value)}
              placeholder="Configured QUIZ_API_HOST_DEMO_TOKEN"
              type="password"
              value={hostToken}
            />
          </label>
          <label>
            Pending round ID
            <input onChange={(event) => setHostRoundId(event.target.value)} value={hostRoundId} />
          </label>
          <label>
            Duration (seconds)
            <input
              max={300}
              min={1}
              onChange={(event) => setDurationSeconds(Number(event.target.value))}
              type="number"
              value={durationSeconds}
            />
          </label>
          <div className="button-row">
            <button
              className="button button--primary"
              disabled={isHostActionRunning}
              onClick={() => void handleHostAction("open")}
              type="button"
            >
              Open round
            </button>
            <button
              className="button button--quiet"
              disabled={isHostActionRunning || activeRound?.status !== "open"}
              onClick={() => void handleHostAction("close")}
              type="button"
            >
              Close round
            </button>
          </div>
        </section>
      </section>

      <section className="quiz-grid">
        <section className="panel question-panel" aria-live="polite">
          <div className="panel-heading question-heading">
            <div>
              <p className="eyebrow">{activeRound?.status ?? "Waiting"}</p>
              <h2>{activeRound === null ? "Waiting for the host" : "Choose the best answer"}</h2>
            </div>
            {timeRemaining !== null ? <strong className="timer">{timeRemaining}s</strong> : null}
          </div>
          {activeRound === null ? (
            <p className="empty-state">Open the seeded round from the host controls to begin.</p>
          ) : (
            <>
              <p className="question-prompt">{activeRound.question.prompt}</p>
              <div className="answers">
                {activeRound.question.options.map((option) => (
                  <button
                    aria-pressed={selectedAnswer === option}
                    className={`answer-option ${selectedAnswer === option ? "answer-option--selected" : ""}`}
                    disabled={activeRound.status !== "open" || answerResult !== null}
                    key={option}
                    onClick={() => setSelectedAnswer(option)}
                    type="button"
                  >
                    {option}
                  </button>
                ))}
              </div>
              <button className="button button--primary answer-submit" disabled={!canSubmit} onClick={() => void handleSubmitAnswer()} type="button">
                {isSubmitting ? "Submitting…" : "Submit answer"}
              </button>
              {answerResult !== null ? (
                <p className={`result ${answerResult.is_correct ? "result--correct" : "result--incorrect"}`}>
                  {answerResult.is_correct ? "Correct" : "Incorrect"} · {answerResult.awarded_points} points · total {answerResult.total_score}
                </p>
              ) : null}
            </>
          )}
        </section>

        <section className="panel leaderboard-panel" aria-live="polite">
          <div className="panel-heading leaderboard-heading">
            <div>
              <p className="eyebrow">Live standings</p>
              <h2>Leaderboard</h2>
            </div>
            <span>{leaderboardTotal} players</span>
          </div>
          {leaderboard.length === 0 ? (
            <p className="empty-state">Standings appear as participants join and answer.</p>
          ) : (
            <ol className="leaderboard-list">
              {leaderboard.map((entry) => (
                <li className={entry.participant_id === participantId ? "leaderboard-entry leaderboard-entry--self" : "leaderboard-entry"} key={entry.participant_id}>
                  <span className="rank">{entry.rank}</span>
                  <span className="player-name">{entry.display_name}</span>
                  <strong>{entry.total_score}</strong>
                </li>
              ))}
            </ol>
          )}
        </section>
      </section>
    </main>
  );
}
