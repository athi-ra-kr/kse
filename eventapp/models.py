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
# Registration counter
# One row per (LEVEL-PREFIX), e.g., "LP-MUS", "UP-FOK"
# -----------------------------
class RegisterCounter(models.Model):
    prefix = models.CharField(max_length=10, unique=True)
    current = models.PositiveIntegerField(default=0)

    def __str__(self) -> str:
        return f"{self.prefix}: {self.current}"


# -----------------------------
# Application (form submissions)
# -----------------------------
class Application(models.Model):
    """
    - program_name is free text like "KG Music", "LP Elocution", "UP Folk Dance", "HS Cinematic Dance".
    - register_no is unique and formatted as <LEVEL>-<PREFIX><NNN>, e.g., LP-MUS001.
    """

    # mirrors first member for legacy fields
    name = models.CharField(max_length=120)   # Member 1 name
    mobile = models.CharField(max_length=20)  # Member 1 mobile

    members = models.JSONField(default=list, blank=True)  # [{name, mobile, alt?}, ...]
    school = models.ForeignKey(School, on_delete=models.PROTECT)

    program_name = models.CharField(max_length=60)

    team_size = models.PositiveIntegerField(default=2)
    register_no = models.CharField(max_length=10, unique=True, editable=False)

    # winners
    is_winner   = models.BooleanField(default=False)
    winner_rank = models.PositiveSmallIntegerField(null=True, blank=True)
    winner_note = models.CharField(max_length=200, blank=True)

    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-submitted_at"]

    def __str__(self) -> str:
        return f"{self.register_no} - {self.name}"

    # ---- Register No helpers ----
    @staticmethod
    def level_for_program(program_name: str) -> str:
        """
        Extracts the level from 'program_name'.
        Supports merged KG (treats LKG/UKG as KG).
        """
        s = (program_name or "").strip().upper()
        if s.startswith("KG "):  return "KG"
        if s.startswith("LP "):  return "LP"
        if s.startswith("UP "):  return "UP"
        if s.startswith("HS "):  return "HS"
        if s.startswith("LKG "): return "KG"
        if s.startswith("UKG "): return "KG"
        return "GEN"

    @staticmethod
    def prefix_for_program(program_name: str) -> str:
        """
        Normalizes program types to 3-letter prefixes.
        New:
          GMU: Group Song
          ELU: Elocution
          FOK: Folk Dance
          CIN: Cinematic Dance
          FAN: Fancy Dress
        Existing:
          MUS: Music
          DAN: (generic/group) Dance
          DRA: Drawing
          GEN: Fallback
        """
        title = (program_name or "").lower()

        # Specific first
        if "group song" in title or "group singing" in title:
            return "GMU"
        if "elocution" in title:
            return "ELU"
        if "folk" in title and "dance" in title:
            return "FOK"
        if ("cinematic" in title or "cinema" in title) and "dance" in title:
            return "CIN"
        if "fancy" in title and "dress" in title:
            return "FAN"

        # Generic
        if "music" in title:
            return "MUS"
        if "drawing" in title:
            return "DRA"
        if "dance" in title:
            return "DAN"

        return "GEN"

    @classmethod
    def next_register_no(cls, program_name: str) -> str:
        """
        Per-(LEVEL, PREFIX) counter.
        Format: <LEVEL>-<PREFIX><NNN>, e.g., LP-MUS001.
        """
        level = cls.level_for_program(program_name)      # KG/LP/UP/HS/GEN
        prefix = cls.prefix_for_program(program_name)    # MUS/DAN/...
        key = f"{level}-{prefix}"                        # stored in RegisterCounter.prefix

        with transaction.atomic():
            counter, _ = RegisterCounter.objects.select_for_update().get_or_create(
                prefix=key, defaults={"current": 0}
            )
            counter.current += 1
            counter.save(update_fields=["current"])
            return f"{level}-{prefix}{counter.current:03d}"


# -----------------------------
# Programme (shown on index)
# -----------------------------
class Programme(models.Model):
    """
    Categories are merged: KG (LKG/UKG together), LP, UP, HS
    """
    CATEGORY_CHOICES = [
        ("KG", "KG"),
        ("LP", "LP"),
        ("UP", "UP"),
        ("HS", "HS"),
    ]

    category     = models.CharField(max_length=10, choices=CATEGORY_CHOICES)
    name         = models.CharField(max_length=120)
    description  = models.TextField(blank=True)
    image        = models.ImageField(upload_to="programme_images/", blank=True, null=True)

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
    link_url = models.URLField(blank=True)
    height_px = models.PositiveIntegerField(default=480)
    order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self) -> str:
        return self.title or f"Banner #{self.pk}"
