// @vitest-environment jsdom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WaterAssistant } from "./water-assistant";

const question = "Explain the synthetic overnight water use.";
const answer = { status: "answer", answer: "These synthetic readings do not prove a physical leak.",
  pending_approval: null, tool_trace: [] };
let root: Root, container: HTMLDivElement;
let calls: { path: string; options: RequestInit }[];
let respond: () => Promise<Response>;

function button(text: string) {
  const element = [...container.querySelectorAll<HTMLButtonElement>("button")]
    .find((item) => item.textContent === text);
  if (!element) throw new Error(`Missing button: ${text}`);
  return element;
}
const input = () => container.querySelector<HTMLTextAreaElement>("#water-question")!;
const turns = () => calls.filter(({ path }) => path.endsWith("/agent/turn"));
async function click(element: HTMLElement) { await act(async () => element.click()); }
async function enterQuestion() {
  await act(async () => root.render(<WaterAssistant scenarioId="overnight-leak" />));
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(input(), question);
    input().dispatchEvent(new Event("input", { bubbles: true }));
  });
}
beforeEach(() => {
  calls = []; respond = async () => Response.json(answer);
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  vi.stubGlobal("fetch", vi.fn(async (url: string, options: RequestInit = {}) => {
    const path = String(url); calls.push({ path, options });
    if (path === "/api/aquamind/v1/sessions") return Response.json({ session_token: "e".repeat(43) });
    if (path === "/api/aquamind/v1/agent/turn") return respond();
    throw new Error(`Unexpected request: ${path}`);
  }));
  container = document.createElement("div"); document.body.append(container); root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount()); container.remove(); vi.unstubAllGlobals();
});

describe("synthetic assistant failure recovery", () => {
  it.each(["401", "429", "503", "network", "malformed"])("focuses a safe error after %s without replaying the question", async (failure) => {
    respond = async () => {
      if (failure === "network") throw new Error("private upstream detail");
      if (failure === "malformed") return Response.json({ ...answer, answer: "" });
      return Response.json({ detail: "private upstream detail" }, { status: Number(failure) });
    };
    await enterQuestion(); await click(button("Send question"));
    const error = container.querySelector('[role="alert"]');
    expect(error?.textContent).toBeTruthy();
    expect(error?.getAttribute("tabindex")).toBe("-1");
    expect(document.activeElement).toBe(error);
    expect(container.textContent).not.toContain("private upstream detail");
    expect(input().value).toBe(question); expect(input().disabled).toBe(false);
    expect(button("Send question").disabled).toBe(false);
    expect(container.textContent).toContain("Approved goal: None this session");
    expect(turns()).toHaveLength(1);
    await act(async () => {});
    expect(turns()).toHaveLength(1);
    respond = async () => Response.json(answer);
    await click(button("Send question"));
    expect(turns()).toHaveLength(2);
    expect(calls.filter(({ path }) => path.endsWith("/sessions"))).toHaveLength(failure === "401" ? 2 : 1);
    expect(container.querySelector('[role="alert"]')).toBeNull();
    expect(container.textContent).toContain(answer.answer);
  });

  it("locks pending actions, keeps their original scenario, then allows an explicit new question", async () => {
    let release!: (value: Response) => void;
    respond = () => new Promise<Response>((resolve) => { release = resolve; });
    await enterQuestion();
    const submit = button("Send question");
    await act(async () => { submit.click(); submit.click(); });
    expect(turns()).toHaveLength(1);
    expect(input().disabled).toBe(true);
    expect(button("Review proposed goal").disabled).toBe(true);
    await act(async () => root.render(<WaterAssistant scenarioId="normal" />));
    expect(JSON.parse(String(turns()[0].options.body)).scenario_id).toBe("overnight-leak");
    expect(container.querySelector('[role="log"]')?.textContent).toContain("Overnight continuous flow");
    await act(async () => release(Response.json({ detail: "private upstream detail" }, { status: 503 })));
    expect(document.activeElement).toBe(container.querySelector('[role="alert"]'));
    expect(button("Review proposed goal").disabled).toBe(false);
    respond = async () => Response.json(answer);
    await click(button("Send question"));
    expect(JSON.parse(String(turns()[1].options.body)).scenario_id).toBe("normal");
    expect(container.querySelector('[role="alert"]')).toBeNull();
    expect(input().value).toBe("");
  });
});
