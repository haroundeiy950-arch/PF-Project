import { useEffect, useRef, useState, type FormEvent } from "react";
import { api } from "../api";
import { useAuth } from "../context/AuthContext";
import { useRealtime } from "../context/RealtimeContext";
import { useDocumentTitle, useResource } from "../hooks/useResource";
import { cx, formatDateTime, formatRelative, initials } from "../lib/format";
import type { Person } from "../types";
import {
  IconCamera,
  IconCheck,
  IconClose,
  IconEdit,
  IconLock,
  IconPeople,
  IconPlus,
  IconRefresh,
  IconSearch,
  IconShield,
  IconTrash,
  IconWarning,
} from "../components/Icons";
import {
  EmptyState,
  ErrorState,
  LoadingState,
  Modal,
  Panel,
  TonePill,
  Toggle,
} from "../components/UI";

export default function People() {
  useDocumentTitle("Authorized People");
  const { can } = useAuth();
  const { pushToast } = useRealtime();
  const [q, setQ] = useState("");
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Person | null>(null);
  const [photoTarget, setPhotoTarget] = useState<Person | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Person | null>(null);
  const [busy, setBusy] = useState(false);

  const meta = useResource(() => api.persons.meta(), []);
  const people = useResource(() => api.persons.list(q || undefined), [q]);

  const engine = meta.data?.face_engine;
  const items = people.data?.items ?? [];

  const openCreate = () => {
    setEditing(null);
    setFormOpen(true);
  };

  const openEdit = (person: Person) => {
    setEditing(person);
    setFormOpen(true);
  };

  const reenroll = async (person: Person) => {
    setBusy(true);
    try {
      const result = await api.persons.reenroll(person.id);
      pushToast({ title: "Face enrollment updated", message: result.message, tone: result.has_embedding ? "success" : "warning" });
      people.reload();
    } catch (error) {
      pushToast({ title: "Enrollment failed", message: error instanceof Error ? error.message : "Request failed", tone: "danger" });
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!deleteTarget) return;
    setBusy(true);
    try {
      await api.persons.remove(deleteTarget.id);
      pushToast({ title: "Person removed", message: `${deleteTarget.full_name} and biometric data deleted`, tone: "success" });
      setDeleteTarget(null);
      people.reload();
    } catch (error) {
      pushToast({ title: "Delete failed", message: error instanceof Error ? error.message : "Request failed", tone: "danger" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="page page--people">
      <div className="page-toolbar">
        <div className="page-toolbar__left">
          <span className="live-chip">
            <span className="live-chip__dot" /> FACE REGISTRY
          </span>
          <span className="muted">
            {people.data?.total ?? 0} enrolled · {people.data?.consented ?? 0} consented · {people.data?.with_embedding ?? 0} with encrypted embedding
          </span>
        </div>
        <div className="page-toolbar__actions">
          <button type="button" className="btn btn--ghost btn--sm" onClick={people.reload}>
            <IconRefresh size={14} /> Refresh
          </button>
          {can("manage_faces") && (
            <button type="button" className="btn btn--primary btn--sm" onClick={openCreate}>
              <IconPlus size={15} /> Enroll person
            </button>
          )}
        </div>
      </div>

      <div className="privacy-banner">
        <span className="privacy-banner__icon"><IconLock size={20} /></span>
        <div>
          <strong>Privacy-first face recognition</strong>
          <p>{meta.data?.consent_notice ?? "Explicit written consent is mandatory before any face template is created."}</p>
        </div>
        <div className="privacy-banner__status">
          <TonePill tone={engine?.enabled && engine?.available ? "green" : engine?.enabled ? "amber" : "muted"}>
            {engine?.enabled ? (engine?.available ? "ENGINE READY" : "ENGINE OPTIONAL") : "DISABLED"}
          </TonePill>
          <span className="mono">threshold {engine?.threshold ?? "—"}</span>
        </div>
      </div>

      <div className="people-layout">
        <div className="people-layout__main">
          <Panel
            title="Authorized personnel"
            subtitle="Known faces are matched only to reduce false alarms — never to raise danger alone"
            actions={
              <label className="search-field search-field--sm">
                <IconSearch size={14} />
                <input value={q} placeholder="Search people…" onChange={(event) => setQ(event.target.value)} />
              </label>
            }
          >
            {people.loading && !people.data ? (
              <LoadingState label="Loading authorized people…" />
            ) : people.error ? (
              <ErrorState message={people.error} retry={people.reload} />
            ) : items.length ? (
              <div className="people-grid">
                {items.map((person) => (
                  <article className={cx("person-card", !person.is_active && "is-inactive")} key={person.id}>
                    <div className="person-card__photo">
                      {person.photo_url ? (
                        <img src={person.photo_url} alt={person.full_name} />
                      ) : (
                        <span className="person-card__initials">{initials(person.full_name)}</span>
                      )}
                      <span className={cx("person-card__badge", person.has_embedding ? "is-biometric" : "is-photo")}>
                        {person.has_embedding ? <IconShield size={12} /> : <IconCamera size={12} />}
                        {person.has_embedding ? "BIOMETRIC" : "PHOTO ONLY"}
                      </span>
                    </div>
                    <div className="person-card__body">
                      <div className="person-card__head">
                        <div>
                          <strong>{person.full_name}</strong>
                          <small>{person.title || "Authorized person"}</small>
                        </div>
                        {!person.is_active && <TonePill tone="muted">INACTIVE</TonePill>}
                      </div>
                      <div className="person-card__facts">
                        <TonePill tone={person.consent_given ? "green" : "red"}>
                          {person.consent_given ? "Consent given" : "No consent"}
                        </TonePill>
                        <span className="mono">{person.consent_at ? formatDateTime(person.consent_at).slice(0, 10) : "not recorded"}</span>
                      </div>
                      {person.notes && <p className="person-card__notes">{person.notes}</p>}
                      <div className="person-card__actions">
                        {can("manage_faces") ? (
                          <>
                            <button type="button" className="btn btn--ghost btn--xs" onClick={() => openEdit(person)}>
                              <IconEdit size={13} /> Edit
                            </button>
                            <button type="button" className="btn btn--ghost btn--xs" onClick={() => setPhotoTarget(person)}>
                              <IconCamera size={13} /> Photo
                            </button>
                            <button
                              type="button"
                              className="btn btn--ghost btn--xs"
                              disabled={busy || !person.consent_given}
                              onClick={() => void reenroll(person)}
                            >
                              <IconRefresh size={13} /> Re-enroll
                            </button>
                            <button type="button" className="icon-btn icon-btn--danger" title="Delete person" onClick={() => setDeleteTarget(person)}>
                              <IconTrash size={14} />
                            </button>
                          </>
                        ) : (
                          <span className="muted">Read-only access</span>
                        )}
                      </div>
                    </div>
                  </article>
                ))}
              </div>
            ) : (
              <EmptyState
                icon={<IconPeople size={28} />}
                title={q ? "No matching people" : "No people enrolled"}
                message={q ? "Try another name or title." : "Enroll staff and residents so their faces can reduce false alarms."}
                action={can("manage_faces") && !q ? <button type="button" className="btn btn--primary btn--sm" onClick={openCreate}><IconPlus size={14} /> Enroll first person</button> : undefined}
              />
            )}
          </Panel>
        </div>

        <aside className="people-layout__side">
          <Panel title="Face engine" subtitle="Optional InsightFace backend" accent={engine?.available ? "green" : "amber"}>
            <div className="engine-status">
              <div className="engine-status__head">
                <span className={cx("status-dot", engine?.available ? "status-dot--online" : "status-dot--warning")} />
                <strong>{engine?.backend ?? "not loaded"}</strong>
              </div>
              <p>{engine?.note ?? "Face recognition is optional and never triggers a danger alarm by itself."}</p>
              <dl className="fact-grid">
                <div>
                  <dt>Status</dt>
                  <dd>{engine?.enabled ? "Enabled" : "Disabled"}</dd>
                </div>
                <div>
                  <dt>Backend</dt>
                  <dd>{engine?.backend ?? "—"}</dd>
                </div>
                <div>
                  <dt>Match threshold</dt>
                  <dd>{engine?.threshold ?? "—"}</dd>
                </div>
                <div>
                  <dt>Embedding storage</dt>
                  <dd>Encrypted</dd>
                </div>
              </dl>
            </div>
            <Toggle
              checked={Boolean(engine?.enabled)}
              onChange={() => pushToast({ title: "Environment setting", message: "Face recognition is enabled in the server environment configuration.", tone: "info" })}
              label="Face recognition"
              description="Enable with FACE_RECOGNITION_ENABLED and install requirements-ai.txt."
            />
          </Panel>

          <Panel title="Enrollment rules" subtitle="What the system will and will not do" accent="amber">
            <ul className="rule-list">
              <li><IconCheck size={14} /><span>Explicit consent is captured before any photo is processed.</span></li>
              <li><IconCheck size={14} /><span>Embeddings are encrypted at rest and never returned by the API.</span></li>
              <li><IconCheck size={14} /><span>Revoking consent immediately deletes the biometric template.</span></li>
              <li><IconWarning size={14} /><span>An unknown face can add at most a small risk contribution.</span></li>
              <li><IconWarning size={14} /><span>Face status alone can never create a critical danger alarm.</span></li>
            </ul>
          </Panel>

          <Panel title="Registry summary" subtitle="Enrollment quality">
            <div className="mini-metrics">
              <div><span>Total</span><strong>{people.data?.total ?? 0}</strong></div>
              <div><span>Consented</span><strong>{people.data?.consented ?? 0}</strong></div>
              <div><span>Embeddings</span><strong>{people.data?.with_embedding ?? 0}</strong></div>
              <div><span>Photos only</span><strong>{Math.max(0, (people.data?.total ?? 0) - (people.data?.with_embedding ?? 0))}</strong></div>
            </div>
            <p className="muted">
              Photo-only records still help operators identify people, but they do not participate in automated matching.
            </p>
          </Panel>
        </aside>
      </div>

      <PersonForm
        open={formOpen}
        person={editing}
        onClose={() => setFormOpen(false)}
        onSaved={() => { setFormOpen(false); people.reload(); }}
        onError={(message) => pushToast({ title: "Enrollment failed", message, tone: "danger" })}
      />

      <PhotoModal
        person={photoTarget}
        onClose={() => setPhotoTarget(null)}
        onSaved={() => { setPhotoTarget(null); people.reload(); }}
        onError={(message) => pushToast({ title: "Photo update failed", message, tone: "danger" })}
      />

      <Modal
        open={Boolean(deleteTarget)}
        onClose={() => setDeleteTarget(null)}
        title="Delete person & biometric data"
        subtitle={deleteTarget?.full_name}
        size="sm"
        footer={
          <div className="modal__footer-row">
            <button type="button" className="btn btn--ghost btn--sm" onClick={() => setDeleteTarget(null)}>Cancel</button>
            <button type="button" className="btn btn--danger btn--sm" disabled={busy} onClick={() => void remove()}>
              {busy ? <span className="spinner spinner--sm" /> : <IconTrash size={14} />} Delete permanently
            </button>
          </div>
        }
      >
        <p className="muted">
          This deletes the person, their photo and the encrypted face template. Existing event history is kept, but the
          person will no longer be recognized as authorized.
        </p>
      </Modal>
    </div>
  );
}

function PersonForm({
  open,
  person,
  onClose,
  onSaved,
  onError,
}: {
  open: boolean;
  person: Person | null;
  onClose: () => void;
  onSaved: () => void;
  onError: (message: string) => void;
}) {
  const [fullName, setFullName] = useState("");
  const [title, setTitle] = useState("");
  const [notes, setNotes] = useState("");
  const [consent, setConsent] = useState(false);
  const [active, setActive] = useState(true);
  const [photo, setPhoto] = useState<File | null>(null);
  const [preview, setPreview] = useState("");
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    setFullName(person?.full_name ?? "");
    setTitle(person?.title ?? "");
    setNotes(person?.notes ?? "");
    setConsent(person?.consent_given ?? false);
    setActive(person?.is_active ?? true);
    setPhoto(null);
    setPreview("");
  }, [open, person]);

  useEffect(() => {
    if (!photo) {
      setPreview("");
      return;
    }
    const url = URL.createObjectURL(photo);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [photo]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    try {
      if (person) {
        await api.persons.update(person.id, {
          full_name: fullName,
          title,
          notes,
          consent_given: consent,
          is_active: active,
        });
        if (photo) {
          const photoForm = new FormData();
          photoForm.append("photo", photo);
          await api.persons.photo(person.id, photoForm);
        }
      } else {
        const form = new FormData();
        form.append("full_name", fullName);
        form.append("title", title);
        form.append("notes", notes);
        form.append("consent_given", consent ? "true" : "false");
        if (photo) form.append("photo", photo);
        await api.persons.create(form);
      }
      onSaved();
    } catch (error) {
      onError(error instanceof Error ? error.message : "The server rejected the enrollment");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={person ? "Edit authorized person" : "Enroll authorized person"}
      subtitle={person ? person.full_name : "Consent-first face registry"}
      size="lg"
      footer={
        <div className="modal__footer-row">
          <button type="button" className="btn btn--ghost btn--sm" onClick={onClose}>Cancel</button>
          <button type="submit" form="person-form" className="btn btn--primary btn--sm" disabled={busy || !fullName.trim()}>
            {busy ? <span className="spinner spinner--sm" /> : <IconCheck size={14} />} {person ? "Save changes" : "Enroll person"}
          </button>
        </div>
      }
    >
      <form id="person-form" className="form-stack" onSubmit={submit}>
        <div className="photo-upload">
          <div className="photo-upload__preview">
            {preview ? (
              <img src={preview} alt="Selected enrollment" />
            ) : person?.photo_url ? (
              <img src={person.photo_url} alt={person.full_name} />
            ) : (
              <span><IconPeople size={28} /></span>
            )}
          </div>
          <div className="photo-upload__body">
            <strong>Enrollment photo</strong>
            <p>Use a clear, front-facing photo with one person. JPG or PNG, up to 8 MB.</p>
            <div className="btn-row">
              <button type="button" className="btn btn--ghost btn--sm" onClick={() => fileRef.current?.click()}>
                <IconCamera size={14} /> {photo ? "Replace selected photo" : "Choose photo"}
              </button>
              {photo && (
                <button type="button" className="btn btn--ghost btn--xs" onClick={() => { setPhoto(null); if (fileRef.current) fileRef.current.value = ""; }}>
                  <IconClose size={13} /> Clear
                </button>
              )}
            </div>
            {photo && <small className="muted">{photo.name} · {(photo.size / 1024).toFixed(0)} KB</small>}
            <input
              ref={fileRef}
              type="file"
              accept="image/jpeg,image/png"
              hidden
              onChange={(event) => setPhoto(event.target.files?.[0] ?? null)}
            />
          </div>
        </div>

        <div className="form-grid">
          <label className="field">
            <span>Full name *</span>
            <input value={fullName} required minLength={2} maxLength={120} onChange={(event) => setFullName(event.target.value)} placeholder="e.g. Sara Al-Amin" />
          </label>
          <label className="field">
            <span>Role / title</span>
            <input value={title} maxLength={120} onChange={(event) => setTitle(event.target.value)} placeholder="e.g. Night shift supervisor" />
          </label>
        </div>

        <label className="field">
          <span>Notes</span>
          <textarea rows={2} value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="Access scope, department, or any operator notes…" />
        </label>

        <div className="consent-box">
          <label className="check-field">
            <input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} />
            <span>
              <strong>Explicit written consent obtained</strong>
              <small>
                The person agreed to biometric face matching for security purposes. Without consent, the photo is stored
                for operator reference only and no embedding is created.
              </small>
            </span>
          </label>
        </div>

        {person && (
          <Toggle
            checked={active}
            onChange={setActive}
            label="Active authorized person"
            description="Inactive people remain on file but are not matched as authorized."
          />
        )}

        <p className="safety-note">
          <IconWarning size={15} />
          Face recognition is an assistance feature. It can never trigger a danger alarm by itself, and all matches must
          be reviewed by an operator.
        </p>
      </form>
    </Modal>
  );
}

function PhotoModal({
  person,
  onClose,
  onSaved,
  onError,
}: {
  person: Person | null;
  onClose: () => void;
  onSaved: () => void;
  onError: (message: string) => void;
}) {
  const [photo, setPhoto] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setPhoto(null);
  }, [person]);

  const submit = async () => {
    if (!person || !photo) return;
    setBusy(true);
    try {
      const form = new FormData();
      form.append("photo", photo);
      await api.persons.photo(person.id, form);
      onSaved();
    } catch (error) {
      onError(error instanceof Error ? error.message : "Photo upload failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={Boolean(person)}
      onClose={onClose}
      title="Replace enrollment photo"
      subtitle={person ? `${person.full_name} · last updated ${formatRelative(person.created_at)}` : undefined}
      size="sm"
      footer={
        <div className="modal__footer-row">
          <button type="button" className="btn btn--ghost btn--sm" onClick={onClose}>Cancel</button>
          <button type="button" className="btn btn--primary btn--sm" disabled={!photo || busy} onClick={() => void submit()}>
            {busy ? <span className="spinner spinner--sm" /> : <IconCamera size={14} />} Upload &amp; re-enroll
          </button>
        </div>
      }
    >
      <div className="form-stack">
        <p className="muted">
          A new photo replaces the old file and recomputes the encrypted face template when consent is on file.
        </p>
        <button type="button" className="photo-drop" onClick={() => fileRef.current?.click()}>
          <IconCamera size={24} />
          <strong>{photo ? photo.name : "Choose a new photo"}</strong>
          <small>JPG or PNG · maximum 8 MB</small>
        </button>
        <input
          ref={fileRef}
          type="file"
          accept="image/jpeg,image/png"
          hidden
          onChange={(event) => setPhoto(event.target.files?.[0] ?? null)}
        />
        {person && !person.consent_given && (
          <p className="safety-note">
            <IconWarning size={15} />
            This person has not given consent. The new photo will be stored for reference only, and no face template
            will be created.
          </p>
        )}
      </div>
    </Modal>
  );
}
