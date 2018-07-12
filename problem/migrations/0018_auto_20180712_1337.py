# -*- coding: utf-8 -*-
# Generated by Django 1.11 on 2018-07-12 13:37
from __future__ import unicode_literals

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('problem', '0017_problem_clone_parent'),
    ]

    operations = [
        migrations.CreateModel(
            name='ProblemContestStatus',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('contest_id', models.PositiveIntegerField(db_index=True)),
                ('ac_user_count', models.PositiveIntegerField()),
                ('total_user_count', models.PositiveIntegerField()),
                ('ac_count', models.PositiveIntegerField()),
                ('total_count', models.PositiveIntegerField()),
                ('difficulty', models.FloatField()),
                ('max_score', models.FloatField()),
                ('avg_score', models.FloatField()),
                ('stats_raw', models.TextField()),
                ('problem', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='problem_contest_status', to='problem.Problem')),
            ],
        ),
        migrations.CreateModel(
            name='ProblemStatus',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('difficulty', models.FloatField()),
                ('ac_user_count', models.PositiveIntegerField()),
                ('total_user_count', models.PositiveIntegerField()),
                ('problem', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='problem_status', to='problem.Problem')),
            ],
        ),
        migrations.CreateModel(
            name='UserStatus',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('contest_id', models.PositiveIntegerField(db_index=True)),
                ('total_count', models.PositiveIntegerField()),
                ('total_list', models.TextField()),
                ('ac_count', models.PositiveIntegerField()),
                ('ac_distinct_count', models.PositiveIntegerField()),
                ('ac_list', models.PositiveIntegerField()),
                ('update_time', models.DateTimeField(auto_now=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='submission_status', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AlterUniqueTogether(
            name='userstatus',
            unique_together=set([('user', 'contest_id')]),
        ),
        migrations.AlterUniqueTogether(
            name='problemconteststatus',
            unique_together=set([('problem', 'contest_id')]),
        ),
    ]
