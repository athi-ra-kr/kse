# eventapp/views.py
from __future__ import annotations

from typing import Tuple
import datetime
import re
import csv

from django.contrib import messages
from django.db import transaction, connection
from django.db.models import Q
from django.http import HttpResponseForbidden, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import Application, Banner, Programme, School


# -----------------------------
# Small helpers
# -----------------------------
def _require_login(request) -> bool:
    return bool(request.session.get("is_logged_in"))


def _redirect_next(request, default_name: str):
    nxt = (request.POST.get("next") or request.GET.get("next") or "").strip()
    if nxt:
        return redirect(nxt)

    referer = (request.META.get("HTTP_REFERER") or "").strip()
    if referer:
        try:
            return redirect(referer)
        except Exception:
            pass

    return redirect(f"eventapp:{default_name}")


def _clamp(n: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, n))


def _split_program_name(program_name: str) -> Tuple[str, str]:
    """
    Application.program_name is like "LKG Dance".
    Returns ("LKG", "Dance"). If it can't, returns ("", program_name).
    """
    s = (program_name or "").strip()
    if not s:
        return "", ""
    parts = s.split(" ", 1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return "", s


def _team_bounds_for_program(program_name: str) -> tuple[int, int]:
    """
    Use Programme.team_min/team_max for the matching programme.
    Falls back to 1..5 (cap for public apply/edit) to match your current rules.
    """
    cat, nm = _split_program_name(program_name)
    q = Programme.objects
    if cat and nm:
        p = q.filter(category=cat, name=nm).only("team_min", "team_max").first()
    else:
        p = q.filter(name=program_name).only("team_min", "team_max").first()

    if p:
        lo = max(1, int(p.team_min or 1))
        hi = min(5, max(lo, int(p.team_max or lo)))
        return lo, hi
    return 1, 5


def _parse_expiry(raw: str | None) -> datetime.date | None:
    """
    Accepts "YYYY-MM-DD" or "DD-MM-YYYY". Returns date or None.
    """
    s = (raw or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _digits_only(s: str) -> str:
    """Remove all non-digits."""
    return re.sub(r"\D+", "", s or "")


def _validate_mobile_10(s: str) -> bool:
    """True iff exactly 10 digits."""
    return bool(re.fullmatch(r"\d{10}", s or ""))


def _flatten_members(app: Application) -> tuple[str, str, str]:
    """
    Return comma-separated strings: (names, mobiles, alt_mobiles)
    Safe against None/empty/malformed members JSON.
    """
    names, mobiles, alts = [], [], []
    try:
        for m in (app.members or []):
            names.append((m.get("name") or "").strip())
            mobiles.append((m.get("mobile") or "").strip())
            alts.append((m.get("alt") or "").strip())
    except Exception:
        # Fallback to legacy single fields
        names = [app.name or ""]
        mobiles = [app.mobile or ""]
        alts = []
    # Remove blank tails for cleaner CSV
    def _clean_join(items): return ", ".join([x for x in items if x])
    return _clean_join(names), _clean_join(mobiles), _clean_join(alts)


# -----------------------------
# Public: Home
# -----------------------------
def index(request):
    banners = Banner.objects.filter(is_active=True).order_by("order", "id")
    first_banner = banners.first()

    # Group active programmes for template
    cats = ["LKG", "UKG", "LP", "UP", "HS"]
    grouped = {c: [] for c in cats}
    qs = Programme.objects.filter(is_active=True).order_by("category", "order", "name")
    for p in qs:
        if p.category in grouped:
            grouped[p.category].append(p)

    # ✅ Show "Winners" nav on index only if winners exist
    winners_count = Application.objects.filter(is_winner=True).count()
    has_winners = winners_count > 0

    ctx = {
        "banners": banners,
        "first_banner": first_banner,
        "programs_by_cat": grouped,
        "schools": School.objects.all().order_by("name"),
        "has_winners": has_winners,         # use this in header to conditionally show Winners link
        "winners_count": winners_count,     # optional badge/count
    }
    return render(request, "index.html", ctx)


# -----------------------------
# Session-based Admin Auth
# -----------------------------
def adminlogin_view(request):
    if request.session.get("is_logged_in"):
        return redirect("eventapp:dashboard")

    if request.method == "POST":
        username = (request.POST.get("username") or "").strip()
        password = (request.POST.get("password") or "").strip()
        if username == "Kseadmin" and password == "Kseadmin":
            request.session["is_logged_in"] = True
            request.session["username"] = username
            return redirect("eventapp:dashboard")
        messages.error(request, "Invalid username or password")
    return render(request, "login.html")


def logout_view(request):
    request.session.flush()
    messages.success(request, "Logged out successfully.")
    return redirect("eventapp:adminlogin")


# -----------------------------
# Apply (public create)
# -----------------------------
def apply(request):
    if request.method != "POST":
        messages.error(request, "Invalid request method.")
        return redirect("eventapp:index")

    program_name = (request.POST.get("program_name") or "").strip()
    school_id = (request.POST.get("school_id") or "").strip()
    team_size = (request.POST.get("team_size") or "").strip()

    if not program_name:
        messages.error(request, "Program is required.")
        return redirect("eventapp:index")

    lo, hi = _team_bounds_for_program(program_name)
    try:
        team_size_i = _clamp(int(team_size or lo), lo, hi)
    except ValueError:
        messages.error(request, f"Team size must be a number between {lo} and {hi}.")
        return redirect("eventapp:index")

    if not school_id:
        messages.error(request, "Please select a valid school.")
        return redirect("eventapp:index")
    school = get_object_or_404(School, pk=school_id)

    members = []
    for i in range(team_size_i):
        n = (request.POST.get(f"members-{i}-name") or "").strip()
        m_raw = (request.POST.get(f"members-{i}-mobile") or "").strip()
        a_raw = (request.POST.get(f"members-{i}-alt") or "").strip()

        if not n or not m_raw:
            messages.error(request, f"Please fill Member {i+1} name and mobile.")
            return redirect("eventapp:index")

        m = _digits_only(m_raw)
        if not _validate_mobile_10(m):
            messages.error(request, f"Member {i+1}: enter a valid 10-digit mobile.")
            return redirect("eventapp:index")

        rec = {"name": n, "mobile": m}

        a = _digits_only(a_raw)
        if a:
            if not _validate_mobile_10(a):
                messages.error(request, f"Member {i+1} alternate: enter a valid 10-digit mobile or leave blank.")
                return redirect("eventapp:index")
            rec["alt"] = a

        members.append(rec)

    try:
        with transaction.atomic():
            regno = Application.next_register_no(program_name)
            app = Application.objects.create(
                name=members[0]["name"],
                mobile=members[0]["mobile"],
                school=school,
                program_name=program_name,
                team_size=team_size_i,
                register_no=regno,
                members=members,
            )
    except Exception as e:
        messages.error(request, f"Something went wrong: {e}")
        return redirect("eventapp:index")

    messages.success(
        request,
        f"✅ Application submitted for <b>{app.program_name}</b>. "
        f"Your <b>Register No</b> is <b>{app.register_no}</b>.",
    )
    return redirect("eventapp:index")


# -----------------------------
# Mini Admin: Dashboard + CRUD (Applications)
# -----------------------------
def dashboard(request):
    if not _require_login(request):
        return redirect("eventapp:adminlogin")

    applications_qs = []
    schools = []
    try:
        tables = set(connection.introspection.table_names())
        if {"eventapp_application", "eventapp_school"} <= tables:
            q = (request.GET.get("q") or "").strip()
            apps = Application.objects.select_related("school").order_by("-submitted_at")

            if q:
                ql = q.lower()
                level_map = {"lkg": "LKG ", "ukg": "UKG ", "lp": "LP ", "up": "UP ", "hs": "HS "}
                if ql in level_map:
                    apps = apps.filter(program_name__istartswith=level_map[ql])
                else:
                    apps = apps.filter(
                        Q(register_no__icontains=q)
                        | Q(name__icontains=q)
                        | Q(mobile__icontains=q)
                        | Q(program_name__icontains=q)
                        | Q(school__name__icontains=q)
                    )
            applications_qs = apps

        if "eventapp_school" in tables:
            schools = School.objects.all().order_by("name")
    except Exception:
        applications_qs = []
        schools = []

    return render(
        request,
        "dashboard.html",
        {
            "username": request.session.get("username", "Admin"),
            "applications": applications_qs,
            "q": request.GET.get("q", "").strip(),
            "schools": schools,
        },
    )


def export_applications_csv(request):
    """
    Export all applications as a CSV file.
    Now includes comma-separated lists of *all* member names, mobiles, and alt mobiles.
    """
    if not request.session.get("is_logged_in"):
        return redirect("eventapp:adminlogin")

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="applications.csv"'
    response.write("\ufeff")  # BOM for Excel

    writer = csv.writer(response)
    writer.writerow([
        "Register No", "Program", "School",
        "Primary Name", "Primary Mobile",
        "Team Size",
        "All Member Names", "All Member Mobiles", "All Member Alt Mobiles",
        "Submitted At",
    ])

    for app in Application.objects.select_related("school").order_by("submitted_at"):
        all_names, all_mobiles, all_alts = _flatten_members(app)
        writer.writerow([
            app.register_no,
            app.program_name,
            app.school.name if app.school else "",
            app.name or "",
            app.mobile or "",
            app.team_size,
            all_names,
            all_mobiles,
            all_alts,
            app.submitted_at.strftime("%Y-%m-%d %H:%M:%S"),
        ])

    return response


def application_edit(request, pk):
    """
    Edit ALL details of an application, including every team member (strict 10-digit mobiles).
    """
    if not _require_login(request):
        return redirect("eventapp:adminlogin")

    app = get_object_or_404(Application, pk=pk)
    schools = School.objects.all().order_by("name")

    if request.method == "POST":
        # Program + school
        app.program_name = (request.POST.get("program_name") or "").strip()
        school_id = (request.POST.get("school_id") or "").strip()
        app.school = get_object_or_404(School, pk=school_id)

        # Team bounds from programme
        lo, hi = _team_bounds_for_program(app.program_name)
        try:
            team_size_i = _clamp(int(request.POST.get("team_size") or lo), lo, hi)
        except ValueError:
            messages.error(request, f"Team size must be a number between {lo} and {hi}.")
            return redirect("eventapp:application_edit", pk=app.pk)

        # Read ALL members with strict 10-digit validation
        members = []
        for i in range(team_size_i):
            n = (request.POST.get(f"members-{i}-name") or "").strip()
            m_raw = (request.POST.get(f"members-{i}-mobile") or "").strip()
            a_raw = (request.POST.get(f"members-{i}-alt") or "").strip()

            if not n or not m_raw:
                messages.error(request, f"Please fill Member {i+1} name and mobile.")
                return redirect("eventapp:application_edit", pk=app.pk)

            m = _digits_only(m_raw)
            if not _validate_mobile_10(m):
                messages.error(request, f"Member {i+1}: enter a valid 10-digit mobile.")
                return redirect("eventapp:application_edit", pk=app.pk)

            rec = {"name": n, "mobile": m}

            a = _digits_only(a_raw)
            if a:
                if not _validate_mobile_10(a):
                    messages.error(request, f"Member {i+1} alternate: enter a valid 10-digit mobile or leave blank.")
                    return redirect("eventapp:application_edit", pk=app.pk)
                rec["alt"] = a

            members.append(rec)

        # Mirror from Member 1 to legacy fields
        app.name = members[0]["name"]
        app.mobile = members[0]["mobile"]

        app.team_size = team_size_i
        app.members = members

        if not (app.name and app.mobile and app.program_name):
            messages.error(request, "Please fill all required fields.")
            return redirect("eventapp:application_edit", pk=app.pk)

        app.save()
        messages.success(request, "✅ Application updated.")
        return redirect("eventapp:dashboard")

    return render(request, "application_edit.html", {"app": app, "schools": schools})


def application_delete(request, pk):
    if not _require_login(request):
        return redirect("eventapp:adminlogin")
    if request.method != "POST":
        return HttpResponseForbidden("Only POST allowed")

    app = get_object_or_404(Application, pk=pk)
    app.delete()
    messages.success(request, f"Application {app.register_no} deleted.")
    return redirect("eventapp:dashboard")


# -----------------------------
# Applications: Winner Update + Printable Card
# -----------------------------
@require_POST
def application_winner_update(request, pk):
    if not request.session.get("is_logged_in"):
        return redirect("eventapp:adminlogin")

    app = get_object_or_404(Application, pk=pk)
    is_winner = request.POST.get("is_winner") == "on"
    winner_rank = request.POST.get("winner_rank") or None
    winner_note = (request.POST.get("winner_note") or "").strip()

    app.is_winner = is_winner
    app.winner_rank = int(winner_rank) if winner_rank else None
    app.winner_note = winner_note
    app.save(update_fields=["is_winner", "winner_rank", "winner_note"])

    messages.success(request, f"✅ Saved winner status for {app.register_no}.")
    return redirect("eventapp:dashboard")


def application_card(request, pk):
    app = get_object_or_404(Application, pk=pk)
    return render(request, "application_card.html", {"app": app})


# -----------------------------
# Schools CRUD
# -----------------------------
def school_list(request):
    if not _require_login(request):
        return redirect("eventapp:adminlogin")

    q = (request.GET.get("q") or "").strip()
    schools = School.objects.all().order_by("name")
    if q:
        schools = schools.filter(name__icontains=q)

    return render(request, "schools.html", {"schools": schools, "q": q})


@require_POST
def school_create(request):
    if not _require_login(request):
        return redirect("eventapp:adminlogin")

    name = (request.POST.get("name") or "").strip()
    if not name:
        messages.error(request, "School name is required.")
        return _redirect_next(request, "school_list")

    try:
        School.objects.get_or_create(name=name)
        messages.success(request, f"✅ School “{name}” added.")
    except Exception as e:
        messages.error(request, f"Could not add school: {e}")
    return _redirect_next(request, "school_list")


@require_POST
def school_update(request, pk):
    if not _require_login(request):
        return redirect("eventapp:adminlogin")

    school = get_object_or_404(School, pk=pk)
    name = (request.POST.get("name") or "").strip()
    if not name:
        messages.error(request, "School name is required.")
        return _redirect_next(request, "school_list")

    try:
        school.name = name
        school.save(update_fields=["name"])
        messages.success(request, "✅ School updated.")
    except Exception as e:
        messages.error(request, f"Could not update: {e}")
    return _redirect_next(request, "school_list")


@require_POST
def school_delete(request, pk):
    if not _require_login(request):
        return redirect("eventapp:adminlogin")

    school = get_object_or_404(School, pk=pk)
    try:
        school.delete()
        messages.success(request, "🗑️ School deleted.")
    except Exception as e:
        messages.error(request, f"Could not delete: {e}")
    return _redirect_next(request, "school_list")


@require_POST
def school_bulk_add(request):
    if not _require_login(request):
        return redirect("eventapp:adminlogin")

    raw = request.POST.get("bulk_names") or ""
    names = [n.strip() for n in raw.splitlines() if n.strip()]

    added = 0
    skipped = 0
    for n in names:
        try:
            _, created = School.objects.get_or_create(name=n)
            if created:
                added += 1
            else:
                skipped += 1
        except Exception:
            skipped += 1

    messages.success(request, f"✅ Bulk add complete. Added: {added}, Skipped: {skipped}.")
    return _redirect_next(request, "school_list")


# -----------------------------
# Programmes CRUD (+ dedicated edit page)
# -----------------------------
def program_list(request):
    if not _require_login(request):
        return redirect("eventapp:adminlogin")

    q = (request.GET.get("q") or "").strip()
    cat = (request.GET.get("cat") or "").strip()

    programs = Programme.objects.all().order_by("category", "order", "name")
    if cat:
        programs = programs.filter(category=cat)
    if q:
        programs = programs.filter(name__icontains=q)

    return render(request, "programmes.html", {"programs": programs, "q": q, "cat": cat})


@require_POST
def program_create(request):
    if not _require_login(request):
        return redirect("eventapp:adminlogin")

    category = (request.POST.get("category") or "").strip()
    name = (request.POST.get("name") or "").strip()
    desc = (request.POST.get("description") or "").strip()
    image = request.FILES.get("image")

    # team range (cap 1..8)
    try:
        team_min = max(1, int(request.POST.get("team_min") or 1))
    except ValueError:
        team_min = 1
    try:
        req_team_max = int(request.POST.get("team_max") or 8)
    except ValueError:
        req_team_max = 8
    team_max = max(team_min, min(8, req_team_max))

    expiry_date = _parse_expiry(request.POST.get("expiry_date"))

    if not (category and name):
        messages.error(request, "Category and Program name are required.")
        return redirect("eventapp:program_list")

    try:
        Programme.objects.create(
            category=category,
            name=name,
            description=desc,
            image=image,
            team_min=team_min,
            team_max=team_max,
            expiry_date=expiry_date,
        )
        messages.success(request, f"✅ Program “{name}” added.")
    except Exception as e:
        messages.error(request, f"Could not add program: {e}")
    return redirect("eventapp:program_list")


@require_POST
def program_update(request, pk):
    if not _require_login(request):
        return redirect("eventapp:adminlogin")

    program = get_object_or_404(Programme, pk=pk)
    program.category = (request.POST.get("category") or "").strip()
    program.name = (request.POST.get("name") or "").strip()
    program.description = (request.POST.get("description") or "").strip()

    # Replace/upload image
    if request.FILES.get("image"):
        program.image = request.FILES.get("image")

    # order / is_active
    order_raw = request.POST.get("order")
    if order_raw not in (None, ""):
        try:
            program.order = int(order_raw)
        except ValueError:
            pass
    if "is_active" in request.POST:
        program.is_active = (request.POST.get("is_active") == "on")

    # team_min/team_max (cap 1..8)
    tmn = request.POST.get("team_min")
    if tmn not in (None, ""):
        try:
            program.team_min = max(1, int(tmn))
        except ValueError:
            pass
    tmx = request.POST.get("team_max")
    if tmx not in (None, ""):
        try:
            requested_max = int(tmx)
            program.team_max = max(program.team_min, min(8, requested_max))
        except ValueError:
            pass

    # expiry date
    if "expiry_date" in request.POST:
        program.expiry_date = _parse_expiry(request.POST.get("expiry_date"))

    if not (program.name and program.category):
        messages.error(request, "Category and Program name are required.")
        return redirect("eventapp:program_list")

    try:
        program.save()
        messages.success(request, f"✅ Program “{program.name}” updated.")
    except Exception as e:
        messages.error(request, f"Could not update: {e}")
    return redirect("eventapp:program_list")


@require_POST
def program_delete(request, pk):
    if not _require_login(request):
        return redirect("eventapp:adminlogin")

    program = get_object_or_404(Programme, pk=pk)
    program.delete()
    messages.success(request, "🗑️ Program deleted.")
    return redirect("eventapp:program_list")


def program_edit_page(request, pk):
    """Dedicated edit page with image replace/remove."""
    if not _require_login(request):
        return redirect("eventapp:adminlogin")

    p = get_object_or_404(Programme, pk=pk)

    if request.method == "POST":
        p.name = (request.POST.get("name") or "").strip()
        p.category = (request.POST.get("category") or "").strip()
        p.description = (request.POST.get("description") or "").strip()

        # Optional extras on the edit page
        try:
            p.order = int(request.POST.get("order") or p.order)
        except ValueError:
            pass
        if "is_active" in request.POST:
            p.is_active = (request.POST.get("is_active") == "on")
        try:
            p.team_min = max(1, int(request.POST.get("team_min") or p.team_min))
        except ValueError:
            pass
        try:
            req_max = int(request.POST.get("team_max") or p.team_max or 8)
            p.team_max = max(p.team_min, min(8, req_max))
        except ValueError:
            pass

        # expiry date
        if "expiry_date" in request.POST:
            p.expiry_date = _parse_expiry(request.POST.get("expiry_date"))

        # Remove image checkbox
        if request.POST.get("image_remove") == "on":
            if p.image:
                p.image.delete(save=False)
            p.image = None

        # Replace/upload image
        if request.FILES.get("image"):
            p.image = request.FILES["image"]

        if not (p.name and p.category):
            messages.error(request, "Category and Program name are required.")
            return redirect("eventapp:program_edit_page", pk=p.pk)

        p.save()
        messages.success(request, "✅ Program updated.")
        return redirect("eventapp:program_list")

    return render(request, "programme_edit.html", {"p": p})


# -----------------------------
# Banners
# -----------------------------
def banner_list(request):
    if not request.session.get("is_logged_in"):
        return redirect("eventapp:adminlogin")

    q = (request.GET.get("q") or "").strip()
    banners = Banner.objects.all().order_by("order", "id")
    if q:
        banners = banners.filter(title__icontains=q)

    return render(request, "banners.html", {"banners": banners, "q": q})


@require_POST
def banner_create(request):
    if not request.session.get("is_logged_in"):
        return redirect("eventapp:adminlogin")

    title = (request.POST.get("title") or "").strip()
    order = int(request.POST.get("order") or 0)
    is_active = request.POST.get("is_active") == "on"
    height_px = int(request.POST.get("height_px") or 480)
    image = request.FILES.get("image")

    if not title:
        messages.error(request, "Title is required.")
        return redirect("eventapp:banner_list")

    Banner.objects.create(
        title=title,
        order=order,
        is_active=is_active,
        height_px=height_px,
        image=image,
    )
    messages.success(request, "✅ Banner added.")
    return redirect("eventapp:banner_list")


@require_POST
def banner_update(request, pk):
    if not request.session.get("is_logged_in"):
        return redirect("eventapp:adminlogin")

    b = get_object_or_404(Banner, pk=pk)
    b.title = (request.POST.get("title") or "").strip()
    try:
        b.order = int(request.POST.get("order") or b.order)
    except ValueError:
        pass
    b.is_active = request.POST.get("is_active") == "on"
    try:
        b.height_px = int(request.POST.get("height_px") or b.height_px)
    except ValueError:
        pass
    if request.FILES.get("image"):
        b.image = request.FILES.get("image")

    b.save()
    messages.success(request, "✅ Banner updated.")
    return redirect("eventapp:banner_list")


@require_POST
def banner_delete(request, pk):
    if not request.session.get("is_logged_in"):
        return redirect("eventapp:adminlogin")

    b = get_object_or_404(Banner, pk=pk)
    b.delete()
    messages.success(request, "🗑️ Banner deleted.")
    return redirect("eventapp:banner_list")


# -----------------------------
# Winners
# -----------------------------
def winners(request):
    """List winners with simple search."""
    if not request.session.get("is_logged_in"):
        return redirect("eventapp:adminlogin")

    q = (request.GET.get("q") or "").strip()
    winners_qs = (
        Application.objects
        .filter(is_winner=True)
        .select_related("school")
        .order_by("winner_rank", "register_no")
    )
    if q:
        winners_qs = winners_qs.filter(
            Q(register_no__icontains=q) |
            Q(name__icontains=q) |
            Q(program_name__icontains=q) |
            Q(school__name__icontains=q)
        )

    return render(request, "winners.html", {"winners": winners_qs, "q": q})


@require_POST
def winners_create(request):
    """Mark an application as winner by Register No, with optional rank/note."""
    if not request.session.get("is_logged_in"):
        return redirect("eventapp:adminlogin")

    reg = (request.POST.get("register_no") or "").strip()
    rank_raw = (request.POST.get("winner_rank") or "").strip()
    note = (request.POST.get("winner_note") or "").strip()

    if not reg:
        messages.error(request, "Register No is required.")
        return redirect("eventapp:winners")

    app = Application.objects.filter(register_no__iexact=reg).first()
    if not app:
        messages.error(request, f"No application found with Register No “{reg}”.")
        return redirect("eventapp:winners")

    app.is_winner = True
    app.winner_note = note
    try:
        app.winner_rank = int(rank_raw) if rank_raw else None
    except ValueError:
        app.winner_rank = None
    app.save(update_fields=["is_winner", "winner_rank", "winner_note"])

    messages.success(request, f"🏆 “{app.register_no}” marked as winner.")
    return redirect("eventapp:winners")


@require_POST
def winners_update(request, pk):
    """Edit rank/note for an existing winner."""
    if not request.session.get("is_logged_in"):
        return redirect("eventapp:adminlogin")

    app = get_object_or_404(Application, pk=pk)
    if not app.is_winner:
        messages.error(request, "This entry is not marked as winner.")
        return redirect("eventapp:winners")

    rank_raw = (request.POST.get("winner_rank") or "").strip()
    note = (request.POST.get("winner_note") or "").strip()

    try:
        app.winner_rank = int(rank_raw) if rank_raw else None
    except ValueError:
        app.winner_rank = None
    app.winner_note = note
    app.save(update_fields=["winner_rank", "winner_note"])

    messages.success(request, f"✅ Winner “{app.register_no}” updated.")
    return redirect("eventapp:winners")


@require_POST
def winners_delete(request, pk):
    """Unmark as winner (soft delete from winners list)."""
    if not request.session.get("is_logged_in"):
        return redirect("eventapp:adminlogin")

    app = get_object_or_404(Application, pk=pk)
    app.is_winner = False
    app.winner_rank = None
    app.winner_note = ""
    app.save(update_fields=["is_winner", "winner_rank", "winner_note"])

    messages.success(request, f"🗑️ “{app.register_no}” removed from winners.")
    return redirect("eventapp:winners")


def winners_export(request):
    """
    Export winners as CSV, including columns with *all* member names,
    mobiles, and alternate mobiles (comma-separated).
    """
    if not request.session.get("is_logged_in"):
        return redirect("eventapp:adminlogin")

    qs = (
        Application.objects
        .filter(is_winner=True)
        .select_related("school")
        .order_by("winner_rank", "register_no")
    )

    # Excel-friendly CSV (BOM)
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = 'attachment; filename="winners.csv"'
    resp.write("\ufeff")  # BOM

    w = csv.writer(resp)
    w.writerow([
        "Register No", "Programme", "School",
        "Primary Name", "Primary Mobile",
        "Team Size",
        "All Member Names", "All Member Mobiles", "All Member Alt Mobiles",
        "Winner Rank", "Winner Note", "Submitted",
    ])

    for a in qs:
        all_names, all_mobiles, all_alts = _flatten_members(a)
        w.writerow([
            a.register_no,
            a.program_name,
            getattr(a.school, "name", ""),
            a.name or "",
            a.mobile or "",
            a.team_size,
            all_names,
            all_mobiles,
            all_alts,
            a.winner_rank or "",
            a.winner_note or "",
            a.submitted_at.strftime("%Y-%m-%d %H:%M"),
        ])

    return resp



# eventapp/views.py (at the end, replace your winnerslist with this)
# eventapp/views.py
def winnerslist(request):
    winners_qs = (
        Application.objects
        .filter(is_winner=True)
        .select_related("school")
        .order_by("winner_rank", "register_no")
    )
    # ensure header shows the Winners link on this page
    ctx = {
        "winners": winners_qs,
        "has_winners": True,
    }
    return render(request, "winnerslist.html", ctx)


