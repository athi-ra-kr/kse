# eventapp/models.py
from django.db import models, transaction
from django.core.exceptions import ValidationError
from django.utils import timezone


# -----------------------------
# Schools
# -----------------------------
class School(models.Model):
    name = models.CharField(max_length=200, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


# -----------------------------
# Registration counter (MUS/DAN/DRA…)
# -----------------------------
class RegisterCounter(models.Model):
    """
    One row per prefix (MUS / DAN / DRA)
    Keeps a single shared counter across all levels (LKG/UKG/LP/UP/HS).
    """
    prefix = models.CharField(max_length=10, unique=True)
    current = models.PositiveIntegerField(default=0)

    def __str__(self) -> str:
        return f"{self.prefix}: {self.current}"


# -----------------------------
# Application (form submissions)
# -----------------------------
class Application(models.Model):
    PROGRAM_CHOICES = [
        ("LKG Music", "LKG Music"),
        ("LKG Dance", "LKG Dance"),
        ("LKG Drawing", "LKG Drawing"),
        ("LKG Group Dance", "LKG Group Dance"),
        ("UKG Music", "UKG Music"),
        ("UKG Dance", "UKG Dance"),
        ("UKG Drawing", "UKG Drawing"),
        ("UKG Group Dance", "UKG Group Dance"),
        ("LP Music", "LP Music"),
        ("LP Dance", "LP Dance"),
        ("LP Drawing", "LP Drawing"),
        ("LP Group Dance", "LP Group Dance"),
        ("UP Music", "UP Music"),
        ("UP Dance", "UP Dance"),
        ("UP Drawing", "UP Drawing"),
        ("UP Group Dance", "UP Group Dance"),
        ("HS Music", "HS Music"),
        ("HS Dance", "HS Dance"),
        ("HS Drawing", "HS Drawing"),
        ("HS Group Dance", "HS Group Dance"),
    ]

    # mirrors first member for legacy fields
    name = models.CharField(max_length=120)   # Member 1 name
    mobile = models.CharField(max_length=20)  # Member 1 mobile

    members = models.JSONField(default=list, blank=True)  # [{name, mobile}, ...]
    school = models.ForeignKey(School, on_delete=models.PROTECT)
    program_name = models.CharField(max_length=40, choices=PROGRAM_CHOICES)

    team_size = models.PositiveIntegerField(default=2)     # validated in view
    register_no = models.CharField(max_length=10, unique=True, editable=False)

    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-submitted_at"]

    def __str__(self) -> str:
        return f"{self.register_no} - {self.name}"

    # ---- register number helpers ----
    @staticmethod
    def prefix_for_program(program_name: str) -> str:
        title = (program_name or "").lower()
        if "music" in title:
            return "MUS"
        if "dance" in title:  # includes Group Dance
            return "DAN"
        if "drawing" in title:
            return "DRA"
        return "GEN"

    @classmethod
    def next_register_no(cls, program_name: str) -> str:
        """
        Transaction-safe: bumps RegisterCounter per prefix and returns e.g. MUS001.
        """
        prefix = cls.prefix_for_program(program_name)
        with transaction.atomic():
            counter, _ = RegisterCounter.objects.select_for_update().get_or_create(
                prefix=prefix, defaults={"current": 0}
            )
            counter.current += 1
            counter.save(update_fields=["current"])
            return f"{prefix}{counter.current:03d}"
# >>> NEW winner fields <<<
    is_winner   = models.BooleanField(default=False)
    winner_rank = models.PositiveSmallIntegerField(null=True, blank=True)
    winner_note = models.CharField(max_length=200, blank=True)

    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-submitted_at"]
# -----------------------------
# Programme (shown on index)
# -----------------------------
class Programme(models.Model):
    CATEGORY_CHOICES = [
        ("LKG", "LKG"),
        ("UKG", "UKG"),
        ("LP",  "LP"),
        ("UP",  "UP"),
        ("HS",  "HS"),
    ]

    category     = models.CharField(max_length=10, choices=CATEGORY_CHOICES)
    name         = models.CharField(max_length=120)
    description  = models.TextField(blank=True)
    image        = models.ImageField(upload_to="programme_images/", blank=True, null=True)

    # Applicants range for Apply modal (replaces old apply_limit)
    team_min     = models.PositiveSmallIntegerField(default=1)
    team_max     = models.PositiveSmallIntegerField(default=5)

    expiry_date  = models.DateField(null=True, blank=True)

    order        = models.PositiveIntegerField(default=0)
    is_active    = models.BooleanField(default=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self) -> str:
        return f"{self.category} — {self.name}"

    def clean(self):
        # enforce 1..5 caps and logical range
        if self.team_min < 1:
            raise ValidationError({"team_min": "Minimum team size must be at least 1."})
        if self.team_max > 5:
            raise ValidationError({"team_max": "Maximum team size cannot exceed 5."})
        if self.team_max < self.team_min:
            raise ValidationError({"team_max": "Maximum must be ≥ minimum."})

    @property
    def is_expired(self) -> bool:
        if not self.expiry_date:
            return False
        return self.expiry_date < timezone.localdate()


# -----------------------------
# Banner (for the hero slider)
# -----------------------------
class Banner(models.Model):
    title = models.CharField(max_length=120, blank=True)
    subtitle = models.CharField(max_length=240, blank=True)
    image = models.ImageField(upload_to="banners/")
    link_url = models.URLField(blank=True)  # optional: click opens this
    height_px = models.PositiveIntegerField(default=480)  # controls slider height
    order = models.IntegerField(default=0)               # sort order (lower = first)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self) -> str:
        return self.title or f"Banner #{self.pk}"
