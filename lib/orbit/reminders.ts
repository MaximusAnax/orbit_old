import { calculateFollowUpAt } from "@/lib/orbit/normalize";
import type { FollowUpActionInput } from "@/lib/validators";

export interface FollowUpTransition {
  profileUpdates: {
    last_interaction_at?: string;
    next_follow_up_at: string | null;
    follow_up_interval_days?: number | null;
  };
  reminderStatus: "contacted" | "snoozed" | "paused";
  dueAt: string | null;
}

export function applyFollowUpAction(
  action: FollowUpActionInput,
  now = new Date(),
  currentIntervalDays = 21,
): FollowUpTransition {
  if (action.action === "mark_contacted") {
    const nextFollowUpAt = calculateFollowUpAt(now, currentIntervalDays);
    return {
      profileUpdates: {
        last_interaction_at: now.toISOString(),
        next_follow_up_at: nextFollowUpAt,
      },
      reminderStatus: "contacted",
      dueAt: nextFollowUpAt,
    };
  }

  if (action.action === "snooze") {
    const dueAt = calculateFollowUpAt(now, action.days);
    return {
      profileUpdates: {
        next_follow_up_at: dueAt,
      },
      reminderStatus: "snoozed",
      dueAt,
    };
  }

  if (action.action === "set_cadence") {
    const dueAt = calculateFollowUpAt(now, action.days);
    return {
      profileUpdates: {
        follow_up_interval_days: action.days,
        next_follow_up_at: dueAt,
      },
      reminderStatus: "snoozed",
      dueAt,
    };
  }

  return {
    profileUpdates: {
      next_follow_up_at: null,
    },
    reminderStatus: "paused",
    dueAt: null,
  };
}

export function shouldSendDailyReminder(input: {
  nextFollowUpAt: string | null;
  alreadySentToday: boolean;
  now?: Date;
}) {
  if (!input.nextFollowUpAt || input.alreadySentToday) return false;
  return new Date(input.nextFollowUpAt).getTime() <= (input.now ?? new Date()).getTime();
}
