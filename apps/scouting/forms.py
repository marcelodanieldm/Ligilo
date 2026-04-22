from __future__ import annotations

from django import forms
from django.forms import BaseFormSet, formset_factory

from apps.scouting.models import Event, Patrol, PatrolMember


INTEREST_CHOICES = [
    ("#Supervivencia", "#Supervivencia"),
    ("#Musica", "#Musica"),
    ("#Programacion", "#Programacion"),
    ("#Cocina", "#Cocina"),
    ("#Deportes", "#Deportes"),
    ("#Naturaleza", "#Naturaleza"),
    ("#PrimerosAuxilios", "#PrimerosAuxilios"),
    ("#Arte", "#Arte"),
    ("#Robotica", "#Robotica"),
    ("#Campismo", "#Campismo"),
]


class PatrolOnboardingStepAForm(forms.ModelForm):
    event = forms.ModelChoiceField(queryset=Event.objects.order_by("-starts_at", "name"))
    interests = forms.MultipleChoiceField(
        required=False,
        choices=INTEREST_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        help_text="Selecciona hasta 5 intereses para matchmaking.",
    )

    class Meta:
        model = Patrol
        fields = [
            "name",
            "delegation_name",
            "country_code",
            "country_name",
            "official_language_code",
            "official_language_name",
            "event",
        ]

    def clean_interests(self):
        interests = self.cleaned_data.get("interests") or []
        if len(interests) > 5:
            raise forms.ValidationError("Puedes seleccionar hasta 5 intereses.")
        return interests


class PatrolMemberForm(forms.Form):
    full_name = forms.CharField(max_length=160, required=False, label="Nombre/Alias")
    alias = forms.CharField(max_length=80, required=False)
    gender = forms.ChoiceField(choices=PatrolMember.Gender.choices, required=False)
    birth_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    initial_level = forms.ChoiceField(choices=PatrolMember.InitialLevel.choices, required=False)

    def clean(self):
        cleaned = super().clean()
        row_has_data = any(cleaned.get(k) for k in ["full_name", "alias", "gender", "birth_date", "initial_level"])
        if not row_has_data:
            return cleaned

        required_fields = ["full_name", "gender", "birth_date", "initial_level"]
        for field in required_fields:
            if not cleaned.get(field):
                self.add_error(field, "Este campo es obligatorio para miembros cargados.")
        return cleaned


class BasePatrolMemberFormSet(BaseFormSet):
    def clean(self):
        super().clean()
        filled = 0
        for form in self.forms:
            if not hasattr(form, "cleaned_data"):
                continue
            if any(form.cleaned_data.get(k) for k in ["full_name", "alias", "gender", "birth_date", "initial_level"]):
                filled += 1

        if filled < 2 or filled > 5:
            raise forms.ValidationError("Debes registrar entre 2 y 5 miembros.")


PatrolMemberFormSet = formset_factory(
    PatrolMemberForm,
    formset=BasePatrolMemberFormSet,
    extra=5,
    max_num=5,
)
