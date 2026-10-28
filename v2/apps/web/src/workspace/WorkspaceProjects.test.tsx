// @vitest-environment jsdom
import React from "react";
import {cleanup, fireEvent, render, screen, waitFor} from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import {afterEach, beforeEach, expect, test, vi} from "vitest";
import {WorkspaceDetails, WorkspaceImporter} from "./WorkspaceProjects";
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), {status, headers:{"content-type":"application/json"}});
const preview = {confirmation_token:"preview-token",archive_sha256:"a".repeat(64),expires_at:2000000000,name:"notebook",include_memory:false,counts:{files:1,artifacts:1,versions:2,messages:2,memory:1,memory_selected:0},source_workspace:{name:"Original project"},omissions:["credentials","active schedules"]};
beforeEach(() => {vi.stubGlobal("React", React);});
afterEach(() => {cleanup();vi.unstubAllGlobals();vi.restoreAllMocks();});
async function selectZip() {fireEvent.change(screen.getByLabelText("Workspace ZIP"),{target:{files:[new File(["synthetic UI transport only"],"notebook.zip",{type:"application/zip"})]}});await waitFor(() => expect(screen.getByRole("button",{name:"Preview import"})).toBeEnabled());}
test("UI-only import previews a new workspace with memory off and never claims resumable execution", async () => {
  const fetcher=vi.fn<(url:string,init?:RequestInit)=>Promise<Response>>(async()=>json(preview));vi.stubGlobal("fetch",fetcher);render(<WorkspaceImporter viewToken={7} onImported={vi.fn()} onCheck={vi.fn()}/>);await selectZip();
  expect(screen.getByLabelText(/Include explicitly saved memory/)).not.toBeChecked();fireEvent.click(screen.getByRole("button",{name:"Preview import"}));await screen.findByLabelText("Snapshot import preview");
  expect(JSON.parse(fetcher.mock.calls[0][1]!.body as string)).toMatchObject({name:"notebook",include_memory:false});expect(screen.getByText(/Memory: off \(1 saved notes omitted/)).toBeVisible();expect(screen.getByText(/Permissions and running tasks are not restored/)).toBeVisible();expect(screen.queryByRole("combobox")).toBeNull();
  fireEvent.click(screen.getByText("What is not restored",{exact:true}));expect(screen.getByText(/not a running agent/)).toBeVisible();expect(screen.getByText("credentials",{exact:true})).toBeVisible();
  fireEvent.click(screen.getByText("Change import choices",{exact:true}));fireEvent.click(screen.getByLabelText(/Include explicitly saved memory/));expect(screen.queryByLabelText("Snapshot import preview")).toBeNull();
});
test("UI-only lost import ACK reuses exactly the same preview choices and request ID", async () => {
  let calls=0;const fetcher=vi.fn<(url:string,init?:RequestInit)=>Promise<Response>>(async(url)=>url.endsWith("/preview")?json(preview):++calls===1?json({detail:"http_503"},503):json({workspace:{id:"new-id",name:"notebook",revision:1},imported:true,lineage:{archive_sha256:preview.archive_sha256},omissions:[]}));vi.stubGlobal("fetch",fetcher);const imported=vi.fn<(result:unknown,token:number)=>Promise<void>>(async()=>{});render(<WorkspaceImporter viewToken={8} onImported={imported} onCheck={vi.fn()}/>);await selectZip();fireEvent.click(screen.getByRole("button",{name:"Preview import"}));await screen.findByLabelText("Snapshot import preview");fireEvent.click(screen.getByRole("button",{name:"Create imported workspace"}));await screen.findByRole("alert");fireEvent.click(screen.getByRole("button",{name:"Create imported workspace"}));await waitFor(()=>expect(imported).toHaveBeenCalledTimes(1));
  const bodies=fetcher.mock.calls.filter(([url])=>url.endsWith("/commit")).map(([,init])=>JSON.parse(init!.body as string));expect(bodies[1]).toEqual(bodies[0]);expect(bodies[0]).toMatchObject({confirmation_token:"preview-token",name:"notebook",include_memory:false});expect(imported.mock.calls[0][1]).toBe(8);
});
test("UI-only invalid archive and mismatched preview never expose a commit action", async()=>{
  vi.stubGlobal("fetch",vi.fn(async()=>json({...preview,name:"different"})));render(<WorkspaceImporter viewToken={1} onImported={vi.fn()} onCheck={vi.fn()}/>);await selectZip();fireEvent.click(screen.getByRole("button",{name:"Preview import"}));await screen.findByRole("alert");expect(screen.queryByRole("button",{name:"Create imported workspace"})).toBeNull();
  fireEvent.change(screen.getByLabelText("Workspace ZIP"),{target:{files:[new File(["data"],"no.txt")]}});expect(screen.getByText(/Choose a Workspace ZIP/)).toBeVisible();expect(screen.getByRole("button",{name:"Preview import"})).toBeDisabled();
});
test("UI-only workspace metadata binds current revision and never archives active work",async()=>{
  const fetcher=vi.fn<(url:string,init?:RequestInit)=>Promise<Response>>(async()=>json({id:"alpha",name:"Renamed",revision:2,archived:false}));vi.stubGlobal("fetch",fetcher);const changed=vi.fn();render(<WorkspaceDetails workspace={{id:"alpha",name:"Original",revision:1}} active={true} onChanged={changed}/>);
  expect(screen.getByRole("button",{name:"Archive workspace"})).toBeDisabled();fireEvent.change(screen.getByLabelText("Workspace name"),{target:{value:"Renamed"}});fireEvent.click(screen.getByRole("button",{name:"Save workspace name"}));await waitFor(()=>expect(changed).toHaveBeenCalledOnce());expect(JSON.parse(fetcher.mock.calls[0][1]!.body as string)).toMatchObject({expected_revision:1,name:"Renamed"});expect(screen.getByText(/does not delete files, revoke permissions/)).toBeVisible();
});
