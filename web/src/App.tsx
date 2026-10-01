import { FormEvent, useCallback, useEffect, useRef, useState } from "react";

import {
  ApiError,
  advanceRound,
  getLeaderboard,
  getQuiz,
  getStreamUrl,
  joinQuiz,
  openRound,
  resetQuiz,
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
const JOIN_KEY_PREFIX = "vocabulary-live:join-key:";

type ConnectionState = "connected" | "connecting" | "disconnected";
type Workspace = "host" | "player";

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

function participantJoinKey(quizId: string): string {
  // Keep one idempotency key per browser session so an existing player can reconnect.
  const storageKey = `${JOIN_KEY_PREFIX}${quizId}`;
  const storedKey = window.sessionStorage.getItem(storageKey);
  if (storedKey !== null) {
    return storedKey;
  }
  const joinKey = crypto.randomUUID();
  window.sessionStorage.setItem(storageKey, joinKey);
  return joinKey;
}

export function App(): JSX.Element {
  const [workspace, setWorkspace] = useState<Workspace>("player");
  const [quizId, setQuizId] = useState(DEMO_QUIZ_ID);
  const [displayName, setDisplayName] = useState("");
  const [hostToken, setHostToken] = useState("");
  const [hostRoundId, setHostRoundId] = useState(DEMO_FIRST_ROUND_ID);
  const [durationSeconds, setDurationSeconds] = useState(120);
  const [isHostLoggedIn, setIsHostLoggedIn] = useState(false);
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
  const [notice, setNotice] = useState("Choose a role to begin the demo.");
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
    void refreshPublicState(DEMO_QUIZ_ID).catch(() => {
      setNotice("Start the FastAPI service, then log in to load the quiz.");
    });
  }, [refreshPublicState]);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    setSelectedAnswer("");
    setAnswerResult(null);
  }, [quiz?.current_round?.id]);

  useEffect(() => {
    if (!isHostLoggedIn) {
      return undefined;
    }

    const pollPublicState = () => {
      void refreshPublicState(quizId).catch((pollError: unknown) => {
        setError(errorMessage(pollError));
      });
    };
    pollPublicState();
    const timer = window.setInterval(pollPublicState, 1_000);
    return () => window.clearInterval(timer);
  }, [isHostLoggedIn, quizId, refreshPublicState]);

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

  function selectWorkspace(nextWorkspace: Workspace): void {
    if (nextWorkspace === workspace) {
      return;
    }
    setWorkspace(nextWorkspace);
    setError(null);
    setIsHostLoggedIn(false);
    setHostToken("");
    setParticipantId(null);
    setParticipantToken(null);
    setStreamPath(null);
    setSelectedAnswer("");
    setAnswerResult(null);
    latestSequence.current = -1;
    setNotice(nextWorkspace === "host" ? "Log in as host to run the quiz." : "Join as a player to answer live questions.");
  }

  async function handleJoin(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const normalizedName = displayName.trim();
    if (normalizedName.length === 0) {
      setError("Enter a display name before joining.");
      return;
    }

    setError(null);
    setIsJoining(true);
    latestSequence.current = -1;
    try {
      const join = await joinQuiz(quizId, normalizedName, participantJoinKey(quizId));
      setParticipantId(join.participant_id);
      setParticipantToken(join.participant_token);
      setStreamPath(join.stream_url);
      await refreshPublicState(join.quiz_id);
      setNotice(`Joined as ${normalizedName}. Your live player stream is connected.`);
    } catch (joinError) {
      setParticipantId(null);
      setParticipantToken(null);
      setError(errorMessage(joinError));
    } finally {
      setIsJoining(false);
    }
  }

  async function handleHostLogin(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (hostToken.trim() === "") {
      setError("Enter the host token to unlock round controls.");
      return;
    }

    setError(null);
    try {
      await refreshPublicState(quizId);
      setIsHostLoggedIn(true);
      setNotice("Host controls unlocked. The server verifies the token when you open or close a round.");
    } catch (loginError) {
      setError(errorMessage(loginError));
    }
  }

  async function handleSubmitAnswer(): Promise<void> {
    const round = quiz?.current_round;
    if (participantToken === null || round === null || selectedAnswer === "") {
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

  async function handleOpenRound(): Promise<void> {
    if (hostRoundId === "") {
      setError("Enter a pending round ID before starting the quiz.");
      return;
    }

    setError(null);
    setIsHostActionRunning(true);
    try {
      await openRound(quizId, hostRoundId, hostToken, durationSeconds);
      setNotice("First question opened. Players receive it through their SSE streams.");
      await refreshPublicState(quizId);
    } catch (openError) {
      setError(errorMessage(openError));
    } finally {
      setIsHostActionRunning(false);
    }
  }

  async function handleAdvanceRound(): Promise<void> {
    setError(null);
    setIsHostActionRunning(true);
    try {
      const result = await advanceRound(quizId, hostToken, durationSeconds);
      setNotice(
        result.completed
          ? "The fifth and final question is closed. The quiz is complete."
          : "Moved all players to the next question.",
      );
      await refreshPublicState(quizId);
    } catch (advanceError) {
      setError(errorMessage(advanceError));
    } finally {
      setIsHostActionRunning(false);
    }
  }

  async function handleResetQuiz(): Promise<void> {
    if (!window.confirm("Reset this quiz? This removes all players, answers, and scores.")) {
      return;
    }

    setError(null);
    setIsHostActionRunning(true);
    try {
      const result = await resetQuiz(quizId, hostToken);
      setNotice(
        `Quiz reset. Removed ${result.removed_participants} players; all five questions are ready again. Players must rejoin.`,
      );
      setHostRoundId(DEMO_FIRST_ROUND_ID);
      await refreshPublicState(quizId);
    } catch (resetError) {
      setError(errorMessage(resetError));
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
    answerResult === null &&
    timeRemaining !== 0;

  return (
    <main className="app-shell">
      <header className="hero">
        <div>
          <p className="eyebrow">Real-time vocabulary quiz</p>
          <h1>Vocabulary Live</h1>
          <p className="subtitle">Choose a role. The shared leaderboard is always public.</p>
        </div>
        {workspace === "player" ? <span className={`connection connection--${connection}`}>{connection}</span> : null}
      </header>

      <nav aria-label="Workspace" className="workspace-tabs">
        <button
          aria-pressed={workspace === "player"}
          className={workspace === "player" ? "workspace-tab workspace-tab--active" : "workspace-tab"}
          onClick={() => selectWorkspace("player")}
          type="button"
        >
          Play quiz
        </button>
        <button
          aria-pressed={workspace === "host"}
          className={workspace === "host" ? "workspace-tab workspace-tab--active" : "workspace-tab"}
          onClick={() => selectWorkspace("host")}
          type="button"
        >
          Host quiz
        </button>
      </nav>

      {error !== null ? <p className="alert alert--error">{error}</p> : null}
      <p className="alert alert--notice">{notice}</p>

      <section className="workspace-grid">
        <section aria-label={workspace === "player" ? "Player workspace" : "Host workspace"} className="workspace-content">
          {workspace === "player" ? (
            participantToken === null ? (
              <form className="panel login-panel" onSubmit={handleJoin}>
                <p className="eyebrow">Player login</p>
                <h2>Join the live quiz</h2>
                <p className="empty-state">Use a separate browser window for every player.</p>
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
                    required
                    value={displayName}
                  />
                </label>
                <button className="button button--primary" disabled={isJoining} type="submit">
                  {isJoining ? "Joining…" : "Join quiz"}
                </button>
              </form>
            ) : (
              <section className="panel question-panel" aria-live="polite">
                <div className="panel-heading question-heading">
                  <div>
                    <p className="eyebrow">Playing as {displayName}</p>
                    <h2>{activeRound === null ? "Waiting for the host" : "Choose the best answer"}</h2>
                  </div>
                  {timeRemaining !== null ? <strong className="timer">{timeRemaining}s</strong> : null}
                </div>
                {activeRound === null ? (
                  <p className="empty-state">The host will open the next round shortly.</p>
                ) : (
                  <>
                    <p className="question-prompt">{activeRound.question.prompt}</p>
                    <div className="answers">
                      {activeRound.question.options.map((option) => (
                        <button
                          aria-pressed={selectedAnswer === option}
                          className={`answer-option ${selectedAnswer === option ? "answer-option--selected" : ""}`}
                          disabled={
                            activeRound.status !== "open" ||
                            answerResult !== null ||
                            timeRemaining === 0
                          }
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
                    {timeRemaining === 0 ? (
                      <p className="result result--incorrect">Time is up. The host will move everyone to the next question.</p>
                    ) : null}
                    {answerResult !== null ? (
                      <p className={`result ${answerResult.is_correct ? "result--correct" : "result--incorrect"}`}>
                        {answerResult.is_correct ? "Correct" : "Incorrect"} · {answerResult.awarded_points} points · total {answerResult.total_score}
                      </p>
                    ) : null}
                  </>
                )}
              </section>
            )
          ) : isHostLoggedIn ? (
            <section className="panel host-panel">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">Host console</p>
                  <h2>Control the next round</h2>
                </div>
                <span className="host-status">Logged in</span>
              </div>
              <p className="empty-state">One question is one round. Advance moves every player together.</p>
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
              {activeRound === null ? (
                <>
                  <label>
                    First pending round ID
                    <input onChange={(event) => setHostRoundId(event.target.value)} value={hostRoundId} />
                  </label>
                  <button
                    className="button button--primary"
                    disabled={isHostActionRunning || quiz?.status === "completed"}
                    onClick={() => void handleOpenRound()}
                    type="button"
                  >
                    {quiz?.status === "completed" ? "Quiz complete — reset to replay" : "Start first question"}
                  </button>
                </>
              ) : (
                <div className="active-round-controls">
                  <p>
                    Question active · {timeRemaining === 0 ? "time expired" : `${timeRemaining ?? "…"} seconds remaining`}
                  </p>
                  <button
                    className="button button--primary"
                    disabled={isHostActionRunning}
                    onClick={() => void handleAdvanceRound()}
                    type="button"
                  >
                    Next question
                  </button>
                </div>
              )}
              <button
                className="button button--danger reset-button"
                disabled={isHostActionRunning}
                onClick={() => void handleResetQuiz()}
                type="button"
              >
                Reset quiz for another test
              </button>
            </section>
          ) : (
            <form className="panel login-panel" onSubmit={handleHostLogin}>
              <p className="eyebrow">Host login</p>
              <h2>Run the quiz</h2>
              <p className="empty-state">Your host token is held only in this browser session.</p>
              <label>
                Quiz ID
                <input value={quizId} onChange={(event) => setQuizId(event.target.value)} required />
              </label>
              <label>
                Host token
                <input
                  onChange={(event) => setHostToken(event.target.value)}
                  placeholder="QUIZ_API_HOST_DEMO_TOKEN"
                  required
                  type="password"
                  value={hostToken}
                />
              </label>
              <button className="button button--primary" type="submit">Log in as host</button>
            </form>
          )}
        </section>

        <section className="panel leaderboard-panel" aria-live="polite">
          <div className="panel-heading leaderboard-heading">
            <div>
              <p className="eyebrow">Public standings</p>
              <h2>Live leaderboard</h2>
            </div>
            <span>{leaderboardTotal} players</span>
          </div>
          <p className="empty-state leaderboard-note">
            {workspace === "host" ? "Refreshes every second for the host." : "Updates through your player SSE stream."}
          </p>
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
