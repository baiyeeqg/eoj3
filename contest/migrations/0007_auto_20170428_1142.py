# -*- coding: utf-8 -*-
# Generated by Django 1.10.4 on 2017-04-28 11:42
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('contest', '0006_contestparticipant_hidden_comment'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='contest',
            name='created_by',
        ),
        migrations.AlterField(
            model_name='contest',
            name='rule',
            field=models.CharField(choices=[('acm', 'ACM Rule'), ('oi', 'OI Rule'), ('oi2', 'Traditional OI Rule'), ('work', 'School Work')], default='acm', max_length=12, verbose_name='Rule'),
        ),
    ]
